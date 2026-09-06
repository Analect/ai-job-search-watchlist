"""Oracle Cloud HCM adapter (recruitingCEJobRequisitions REST API).

ats_config shape: {"host": "<tenant>.fa.<region>.oraclecloud.com", "site": "<career-site-id>"}
(e.g. {"host": "jpmc.fa.oraclecloud.com", "site": "CX_1001"}).

Not to be confused with Taleo — Oracle acquired Taleo Corp in 2012 and
still runs it as a genuinely separate, older ATS product alongside this
newer, Oracle-native Fusion Cloud HCM Recruiting module; they have
different APIs and jseek treats them as distinct monitor/scraper types
(`taleo.py` vs `oracle_hcm.py`). Zero of our 69 shortlisted employers use
Taleo (confirmed against the wider 2,747-company tech/finance/prof-
services universe: only one company anywhere uses it, and they're not on
our list), so it's out of scope entirely.

jseek's real `core/monitors/oracle_hcm.py` is built for scale far beyond
our 2 employers: multi-facet-partition pagination past Oracle's 10,000-
result window, offset-overlap/duplicate-row/page-shortfall tolerances,
and orchestrating multiple boards' shared-infra outages. Both our
employers are well under the 10,000 cap (Goldman Sachs CampusHiring:
1,322; JPMorgan CX_1001: 7,328 - confirmed live), so none of that
completeness machinery is needed. What IS reused, since it's a real
documented API behavior rather than a jseek-internal design choice:

- `TotalJobsCount` IS stable across pages here (confirmed live - unlike
  Workday's per-page reset), but dlt's `OffsetPaginator` still doesn't
  fit this API: Oracle expects `offset` embedded INSIDE the compound
  `finder=findReqs;siteNumber=X,offset=N,limit=200` query value, not as
  a separate top-level query param - confirmed live that appending a
  plain `?offset=N` is silently ignored (every "page" returned an
  identical first 200 results). Manual pagination instead, matching
  jseek's own proven `f"{source_url},offset={offset}"` string-append
  approach - dlt's pagination helpers are used where the API shape
  actually fits them (Workday's POST-JSON-body offset), not forced onto
  every adapter regardless of fit.
- A 403 here is retried, not treated as an immediate anti-bot block:
  jseek's own postmortem (Albertsons #6394) found Oracle's shared
  multi-tenant infrastructure produces transient Akamai 403s that
  succeed on an identical retry - genuinely different from Eightfold's
  sustained per-tenant WAF block. `fetch_json_with_retry`'s
  `retryable_403=True` was added specifically for this.
- The list response already includes `PrimaryLocation` per item for
  free (e.g. "Jersey City, NJ, United States") - same "filter before
  the expensive fetch" principle as Workday/Eightfold: only spend a
  per-job detail fetch (full description) on postings matching
  TARGET_CITIES, not all 7,328 of JPMorgan's worldwide postings.
- Full description needs jseek's own scraper's detail endpoint
  (`recruitingCEJobRequisitionDetails`) - the list response's own
  `ShortDescriptionStr` is a one-line teaser, not the real description.
  Its field-fallback chain (`ExternalDescriptionStr ||
  OrganizationDescriptionStr || CorporateDescriptionStr`) is reused
  verbatim - some tenants leave the role-specific field blank while
  still populating org-level description text.
"""

from collections.abc import Iterator
from typing import Any

from pipelines.common.http_retry import fetch_json_with_retry
from pipelines.common.target_cities import TARGET_CITIES
from pipelines.common.text_clean import clean_description, clean_text
from pipelines.common.types import Employer

_PAGE_SIZE = 200


def _list_url_path(site: str) -> str:
    return (
        "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        f"?onlyData=true&expand=requisitionList.workLocation"
        f"&finder=findReqs;siteNumber={site},limit={_PAGE_SIZE},sortBy=POSTING_DATES_DESC"
    )


def _detail_url(host: str, site: str, req_id: str) -> str:
    return (
        f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
        f'?expand=all&onlyData=true&finder=ById;Id="{req_id}",siteNumber={site}'
    )


def _job_url(host: str, site: str, req_id: str) -> str:
    return f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{req_id}"


def _location_matches_target(primary_location: str | None) -> bool:
    """Same exact-segment-match principle as the shared gazetteer -
    PrimaryLocation is formatted "City, Region, Country"."""
    if not primary_location:
        return False
    leading = primary_location.split(",", 1)[0].strip().casefold()
    return leading in TARGET_CITIES


def _list_postings(host: str, site: str) -> list[dict]:
    # dlt's OffsetPaginator doesn't fit this API: Oracle expects offset
    # embedded INSIDE the compound `finder=findReqs;...,offset=N` query
    # value, not as a separate top-level query param - confirmed live
    # that appending a plain `?offset=N` is silently ignored (every
    # "page" returned an identical first 200 results: 1400 items
    # fetched, only 200 unique IDs). Manual pagination instead, matching
    # jseek's own proven `f"{source_url},offset={offset}"` approach.
    base_url = f"https://{host}{_list_url_path(site)}"
    offset = 0
    postings: list[dict] = []
    total = None
    while total is None or offset < total:
        url = f"{base_url},offset={offset}" if offset else base_url
        data = fetch_json_with_retry("GET", url, retryable_403=True)
        wrapper = (data.get("items") or [{}])[0]
        if total is None:
            total = wrapper.get("TotalJobsCount") or 0
            if total <= 0:
                return []
        items = wrapper.get("requisitionList", [])
        if not items:
            break
        postings.extend(items)
        offset += len(items)
    return postings


def fetch_postings(employer: Employer) -> Iterator[dict[str, Any]]:
    host = employer.ats_config.get("host")
    site = employer.ats_config.get("site")
    if not (host and site):
        return

    for item in _list_postings(host, site):
        req_id = item.get("Id")
        if not req_id:
            continue
        req_id = str(req_id)
        primary_location = item.get("PrimaryLocation")
        if not _location_matches_target(primary_location):
            continue  # server-side-free filter: skip the expensive detail fetch entirely

        description_text = None
        try:
            detail = fetch_json_with_retry(
                "GET",
                _detail_url(host, site, req_id),
                retries=1,
                raise_on_404=False,
                retryable_403=True,
            )
            detail_item = (detail.get("items") or [{}])[0]
            description_text = clean_description(
                detail_item.get("ExternalDescriptionStr")
                or detail_item.get("OrganizationDescriptionStr")
                or detail_item.get("CorporateDescriptionStr")
            )
        except Exception:
            pass

        work_locations = item.get("workLocation") or []
        primary_work = work_locations[0] if work_locations else {}

        yield {
            "external_id": req_id,
            "title": clean_text(item.get("Title")),
            "source_url": _job_url(host, site, req_id),
            "location_raw": clean_text(primary_location),
            "location_city": primary_work.get("TownOrCity"),
            "location_region": primary_work.get("Region2") or primary_work.get("Region1"),
            "location_country": primary_work.get("Country"),
            "employment_type": clean_text(item.get("JobSchedule")),
            "posted_date": (item.get("PostedDate") or "")[:10] or None,
            "description_text": description_text,
        }
