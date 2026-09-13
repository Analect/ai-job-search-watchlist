"""Workday adapter.

ats_config shape: {"company": "...", "wd_instance": "wd5", "site": "..."}

jseek's real `core/monitors/workday.py` is extremely elaborate: multi-site
discovery via robots.txt, a 2000-result-per-query cap handled via
multi-dimension "facet_union" completeness proofs, SSL-verification
retries, and strict fail-closed assertions — built for crawling hundreds
of diverse enterprise tenants with completeness guarantees at scale.
Disproportionate for our 16 employers. This is a deliberately simplified,
single-site design, but every real API quirk below was confirmed live,
not assumed:

- The list endpoint (`POST .../wday/cxs/{company}/{site}/jobs`) returns
  `total` correctly on the FIRST page only - on every subsequent page,
  `total` resets to 0 (confirmed live against both a small tenant,
  G-Research, and a large one, NVIDIA - not facet-specific). dlt's
  `OffsetPaginator` with `total_path="total"` re-reads this on every
  page and would silently stop after 2 pages (40 jobs) for EVERY
  employer if used naively. Worked around by probing the first page
  ourselves for the true `total`, then building the real paginator with
  a fixed `maximum_offset` and `total_path=None` so it never re-trusts
  Workday's own flaky per-page total. jseek's own monitor has the exact
  same guard (`if offset == 0: total = data.get("total", 0)`) - this
  independently confirms it's a genuine, general Workday quirk, not
  something specific to how we're querying it.
- Some tenants cap `total` at 2000 regardless of the real count
  (confirmed live: NVIDIA reports exactly `"total": 2000`). One round
  of facet-splitting (not jseek's full multi-dimension "facet_union"
  proof) is applied when this cap is hit: pick the facet with the most
  values where no single value's own count is itself capped, group
  values into batches whose summed (already-known, from the capped
  query's own facets) counts stay under 2000, then run one paginated
  fetch per batch with `appliedFacets` in the request body. Extra JSON
  body keys DO survive across dlt's paginated requests (confirmed via
  the actual request body sent on each page) - the `total` quirk above
  is Workday's own bug, not a dlt limitation.
- Detail fetch (`GET .../wday/cxs/{company}/{site}/job/{externalPath}`)
  needs `Accept: application/json` (same class of issue as Lever).
  A 404, or a 403 whose JSON body has `errorCode: "S22"`, means the
  posting was delisted between the list and detail fetch - jseek's own
  scraper treats this as "gone" (skip silently), not a hard failure;
  reused verbatim rather than re-derived.
- Location strings are stored raw (e.g. "US-AR-SPRINGDALE-BLDG 1 ~ 275 E
  Robinson Ave" or "New York  New York  United States") rather than
  replicating jseek's own elaborate multi-format location parser - the
  "raw + view" pattern every other adapter here already uses; the
  shared London/Dublin gazetteer still catches what it can.
- Some of our 16 employers have thousands of open postings worldwide
  (confirmed live: NVIDIA 2691, Capital One 1893, Morgan Stanley 1310,
  Barclays 950) - fetching every posting's full detail (N+1) on every
  scheduled run would mean 9,000+ requests, taking many minutes, for
  data this project (a London/Dublin watchlist) doesn't need. Workday's
  own `locations` facet already gives every posting's office assignment
  for free in the initial query (no detail fetch needed to see it), so
  this is used as a SERVER-SIDE pre-filter: only office values whose
  descriptor's leading comma-segment is exactly "london" or "dublin"
  (confirmed live: descriptors are building-level, e.g. "London, Luke
  Street (Eagle Lab)", "Dublin, Molesworth Street" - a plain substring
  match on "london" would also match unrelated street names like
  "Lowestoft, London Road North", same class of bug fixed in the shared
  gazetteer). Falls back to the unfiltered facet-splitting path only if
  a tenant doesn't expose a `locations` facet at all (not yet observed
  across any of our 14 configured employers, but a reasonable safety
  net rather than silently returning zero on an unexpected shape).
"""

from collections.abc import Iterator
from typing import Any

from dlt.sources.helpers.rest_client import RESTClient
from dlt.sources.helpers.rest_client.paginators import OffsetPaginator

from pipelines.common.http_retry import fetch_json_with_retry
from pipelines.common.target_cities import CITY_ALIASES, TARGET_CITIES
from pipelines.common.text_clean import clean_description, clean_text
from pipelines.common.types import Employer

_PAGE_SIZE = 20
_API_RESULT_CAP = 2000
_DETAIL_HEADERS = {"Accept": "application/json"}


def _base_url(company: str, wd_instance: str) -> str:
    return f"https://{company}.{wd_instance}.myworkdayjobs.com"


def _list_path(company: str, site: str) -> str:
    return f"/wday/cxs/{company}/{site}/jobs"


def _detail_url(company: str, wd_instance: str, site: str, external_path: str) -> str:
    return f"https://{company}.{wd_instance}.myworkdayjobs.com/wday/cxs/{company}/{site}{external_path}"


def _iter_facets(facets: list[dict]):
    for facet in facets:
        if not isinstance(facet, dict):
            continue
        yield facet
        nested = [
            v for v in facet.get("values", []) if isinstance(v, dict) and v.get("facetParameter")
        ]
        yield from _iter_facets(nested)


def _location_leading_segment(descriptor: str) -> str:
    """First comma-delimited segment of a Workday location descriptor,
    trimmed/casefolded - same exact-segment-match principle as the shared
    gazetteer's fix, applied here to structured facet values instead of
    free-text location_raw.

    Some tenants omit the comma separator entirely, using one of:
    - city + country with double-spaces: "London  United Kingdom" (Citi)
    - city + qualifier with a space:    "Dublin Office - George's Quay House" (Fidelity)
    - building name only:               "Cannon Street Office" (Fidelity)

    For these, comma-split returns the whole string; two fallbacks resolve them:
    1. First whitespace token — catches "london" / "dublin" directly.
    2. Alias-prefix check — catches "cannon street office" via the
       "cannon street" → "london" alias in CITY_ALIASES.
    """
    segment = descriptor.split(",", 1)[0].strip().casefold()
    # Direct match or alias on the whole comma-segment (standard case)
    key = CITY_ALIASES.get(segment, segment)
    if key in TARGET_CITIES:
        return key
    # Tenants that omit the comma: try the first whitespace token
    tokens = segment.split()
    if tokens:
        first = CITY_ALIASES.get(tokens[0], tokens[0])
        if first in TARGET_CITIES:
            return first
    # Alias-prefix: "cannon street office".startswith("cannon street") → "london"
    for alias, canonical in CITY_ALIASES.items():
        if segment.startswith(alias):
            return canonical
    return segment


def _target_location_ids(facets: list[dict]) -> list[str]:
    """IDs of every `locations` facet value whose office is in a
    TARGET_CITIES city. Returns [] if the facet exists but has no
    matches (genuinely no relevant offices); the caller distinguishes
    "facet absent" from "facet present, no matches" to decide whether
    to fall back."""
    ids: list[str] = []
    for facet in _iter_facets(facets):
        if facet.get("facetParameter") != "locations":
            continue
        for v in facet.get("values", []):
            descriptor = v.get("descriptor", "")
            if _location_leading_segment(descriptor) in TARGET_CITIES and v.get("id"):
                ids.append(v["id"])
    return ids


def _has_locations_facet(facets: list[dict]) -> bool:
    return any(f.get("facetParameter") == "locations" for f in _iter_facets(facets))


def _pick_split_facet(facets: list[dict]) -> tuple[str, list[tuple[str, int]]] | None:
    """Adapted from jseek's own `_pick_split_facet` (unpreferred branch):
    picks the facet with the most values where no single value's count is
    itself >= the cap, so each sub-query stays under it."""
    best: tuple[str, list[tuple[str, int]]] | None = None
    best_count = 0
    for facet in _iter_facets(facets):
        param = facet.get("facetParameter")
        values = facet.get("values", [])
        if not param or not values:
            continue
        if any(v.get("count", 0) >= _API_RESULT_CAP for v in values):
            continue
        pairs = [(v["id"], v.get("count", 0)) for v in values if "id" in v]
        if len(pairs) > best_count:
            best = (param, pairs)
            best_count = len(pairs)
    return best


def _group_facet_values(pairs: list[tuple[str, int]]) -> list[list[str]]:
    """Bin-pack facet value ids into query groups whose summed known
    counts stay under the cap (adapted from jseek's `_group_split_facet_values`)."""
    groups: list[list[str]] = []
    current: list[str] = []
    current_count = 0
    for facet_id, count in pairs:
        if current and current_count + count >= _API_RESULT_CAP:
            groups.append(current)
            current = []
            current_count = 0
        current.append(facet_id)
        current_count += count
    if current:
        groups.append(current)
    return groups


def _paginate(base_url: str, path: str, body: dict, maximum_offset: int) -> list[dict]:
    if maximum_offset <= 0:
        return []
    client = RESTClient(base_url=base_url)
    paginator = OffsetPaginator(
        limit=_PAGE_SIZE,
        offset=0,
        offset_body_path="offset",
        limit_body_path="limit",
        total_path=None,  # Workday's own `total` resets to 0 after page 1 - see module docstring
        maximum_offset=maximum_offset,
    )
    postings: list[dict] = []
    for page in client.paginate(
        path,
        method="POST",
        json={**body, "limit": _PAGE_SIZE, "offset": 0},
        paginator=paginator,
        data_selector="jobPostings",
    ):
        postings.extend(page)
    return postings


def _fetch_capped(
    base_url: str, path: str, base_body: dict, total: int, facets: list[dict]
) -> list[dict]:
    """Paginate a query, splitting by one additional facet if it hit the
    2000 cap (jseek's own `_pick_split_facet`/`_group_split_facet_values`
    logic, adapted - see module docstring)."""
    if total < _API_RESULT_CAP:
        return _paginate(base_url, path, base_body, total)

    split = _pick_split_facet(facets)
    if not split:
        return _paginate(base_url, path, base_body, _API_RESULT_CAP)

    facet_param, pairs = split
    groups = _group_facet_values(pairs)
    seen_paths: set[str] = set()
    postings: list[dict] = []
    for group in groups:
        group_total = sum(count for facet_id, count in pairs if facet_id in group)
        combined_body = {
            **base_body,
            "appliedFacets": {**base_body.get("appliedFacets", {}), facet_param: group},
        }
        group_postings = _paginate(base_url, path, combined_body, group_total)
        for p in group_postings:
            path_key = p.get("externalPath")
            if path_key and path_key not in seen_paths:
                seen_paths.add(path_key)
                postings.append(p)
    return postings


def _list_postings(company: str, wd_instance: str, site: str) -> list[dict]:
    base_url = _base_url(company, wd_instance)
    path = _list_path(company, site)
    probe = fetch_json_with_retry("POST", f"{base_url}{path}", json_body={"limit": 1, "offset": 0})
    facets = probe.get("facets", [])

    if _has_locations_facet(facets):
        location_ids = _target_location_ids(facets)
        if not location_ids:
            return []  # genuinely no London/Dublin offices for this tenant
        body = {"appliedFacets": {"locations": location_ids}}
        filtered_probe = fetch_json_with_retry(
            "POST", f"{base_url}{path}", json_body={**body, "limit": 1, "offset": 0}
        )
        return _fetch_capped(
            base_url, path, body, filtered_probe.get("total", 0), filtered_probe.get("facets", [])
        )

    # No `locations` facet exposed at all for this tenant - safety-net
    # fallback to the unfiltered path (not observed across any of our 14
    # configured employers, but avoids silently returning zero on an
    # unexpected facet shape).
    return _fetch_capped(base_url, path, {}, probe.get("total", 0), facets)


def fetch_postings(employer: Employer) -> Iterator[dict[str, Any]]:
    company = employer.ats_config.get("company")
    wd_instance = employer.ats_config.get("wd_instance")
    site = employer.ats_config.get("site")
    if not (company and wd_instance and site):
        return

    for item in _list_postings(company, wd_instance, site):
        external_path = item.get("externalPath")
        if not external_path:
            continue
        req_id = (item.get("bulletFields") or [None])[0]

        description_text = None
        location_raw = clean_text(item.get("locationsText"))
        employment_type = None
        posted_date = None
        try:
            detail = fetch_json_with_retry(
                "GET",
                _detail_url(company, wd_instance, site, external_path),
                headers=_DETAIL_HEADERS,
                raise_on_404=False,
            )
            info = detail.get("jobPostingInfo") or {}
            if info:
                description_text = clean_description(info.get("jobDescription"))
                location_raw = clean_text(info.get("location")) or location_raw
                employment_type = clean_text(info.get("timeType"))
                posted_date = info.get("startDate")
        except Exception:
            # jseek's own scraper treats a 403 with errorCode=S22 the same
            # as a 404: the posting was delisted between list and detail
            # fetch. fetch_json_with_retry doesn't parse the body on a
            # non-2xx to check for S22 specifically, so any detail-fetch
            # failure here just falls back to the list-only fields already
            # captured above rather than dropping the posting entirely.
            pass

        yield {
            "external_id": req_id or external_path,
            "title": clean_text(item.get("title")),
            "source_url": _job_url(company, wd_instance, site, external_path),
            "location_raw": location_raw,
            "employment_type": employment_type,
            "posted_date": (posted_date or "")[:10] or None,
            "description_text": description_text,
        }


def _job_url(company: str, wd_instance: str, site: str, external_path: str) -> str:
    return f"https://{company}.{wd_instance}.myworkdayjobs.com/{site}{external_path}"
