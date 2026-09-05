"""Eightfold adapter.

ats_config shape: {"host": "<eightfold-tenant-host>"} (e.g.
"career.mlp.com" or "lamresearch.eightfold.ai").

jseek's real `core/monitors/eightfold.py` uses a private "PCSX" search
API with incremental watermarking, WAF-block detection, and disabled-
tenant caching - built for crawling thousands of companies at a
rate-limit-sensitive scale. That's disproportionate for our 2 Eightfold
employers, so this is a from-scratch, deliberately simplified design
(no watermark, always a full fetch), confirmed against BOTH real
tenants rather than assumed to work identically:

1. **Public jobs API** (works for millennium-management/mlp.com):
   `GET https://{host}/careers` to scrape `window._EF_GROUP_ID` (the
   API's "domain" param is this group id, NOT the tenant hostname -
   confirmed live: "domain=career.mlp.com" 404s, "domain=mlp.com"
   works), then paginate `GET /api/apply/v2/jobs?domain={group_id}&start=N&num=100`,
   then a per-job `GET /api/apply/v2/jobs/{id}?domain={group_id}` for
   the full HTML description (the list response's own job_description
   field is always empty - confirmed live, matches jseek's own
   PCSX-doesn't-return-descriptions note).
2. **Sitemap + JSON-LD fallback** (needed for lam-research: its tenant
   returns `{"message": "Not authorized for PCSX"}` for the public API
   regardless of host): `GET /careers/sitemap.xml` for the full job URL
   set, then a per-job page fetch parsing the standard schema.org
   `JobPosting` JSON-LD block already embedded in the static HTML (no
   JS rendering needed - same "no browser needed" property every other
   adapter in this repo relies on).
"""

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import requests

from pipelines.common.http_retry import fetch_json_with_retry
from pipelines.common.text_clean import clean_description, clean_text
from pipelines.common.types import Employer

_GROUP_ID_RE = re.compile(r"window\._EF_GROUP_ID\s*=\s*[\"']([^\"']+)[\"']")
_JSONLD_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)
_SITEMAP_JOB_URL_RE = re.compile(r"<loc>\s*(https?://[^<]*?/careers/job/[^<]+)\s*</loc>")
_JOB_ID_FROM_URL_RE = re.compile(r"/careers/job/(\d+)")


def _group_id(host: str) -> str | None:
    resp = requests.get(f"https://{host}/careers", timeout=30)
    resp.raise_for_status()
    match = _GROUP_ID_RE.search(resp.text)
    return match.group(1) if match else None


def _fetch_via_public_api(host: str, group_id: str) -> Iterator[dict[str, Any]] | None:
    """Returns None (not a generator) if this tenant blocks the public
    API, so the caller can fall back to sitemap scraping instead."""
    try:
        probe = fetch_json_with_retry(
            "GET",
            f"https://{host}/api/apply/v2/jobs",
            params={"domain": group_id, "start": 0, "num": 1},
            retries=1,
            raise_on_404=False,
        )
    except Exception:
        # Some tenants block this endpoint outright (WAF/403, not just a
        # 200-with-"Not authorized" body) - jseek's own PcsxStableBlock
        # case, confirmed live for lam-research (403 Forbidden). Either
        # shape means the same thing: fall back to sitemap scraping.
        return None
    if isinstance(probe, dict) and "Not authorized" in str(probe.get("message", "")):
        return None
    return _public_api_postings(host, group_id)


def _public_api_postings(host: str, group_id: str) -> Iterator[dict[str, Any]]:
    start = 0
    page_size = 100
    while True:
        data = fetch_json_with_retry(
            "GET",
            f"https://{host}/api/apply/v2/jobs",
            params={"domain": group_id, "start": start, "num": page_size},
        )
        positions = data.get("positions", [])
        for pos in positions:
            job_id = pos.get("id")
            description_text = None
            try:
                detail = fetch_json_with_retry(
                    "GET",
                    f"https://{host}/api/apply/v2/jobs/{job_id}",
                    params={"domain": group_id},
                    retries=1,
                    raise_on_404=False,
                )
                description_text = clean_description(detail.get("job_description"))
            except Exception:
                pass
            t_create = pos.get("t_create")
            yield {
                "external_id": str(job_id),
                "title": clean_text(pos.get("name")),
                "source_url": pos.get("canonicalPositionUrl"),
                "location_raw": clean_text(", ".join(pos.get("locations") or [])),
                "department": clean_text(pos.get("department")),
                "is_remote": (pos.get("work_location_option") == "remote") or None,
                "posted_date": None
                if not t_create
                else datetime.fromtimestamp(t_create, tz=UTC).date().isoformat(),
                "description_text": description_text,
            }
        if not positions:
            break
        # The API silently caps each page at some server-side size
        # regardless of the requested `num` (confirmed live: num=100
        # still returns only 10 positions/page) - advance by the
        # actual count returned, and stop once we've reached the
        # response's own reported total rather than trusting `num`.
        start += len(positions)
        total = data.get("count")
        if total is not None and start >= total:
            break


def _sitemap_postings(host: str) -> Iterator[dict[str, Any]]:
    resp = requests.get(f"https://{host}/careers/sitemap.xml", timeout=30)
    resp.raise_for_status()
    urls = sorted(set(_SITEMAP_JOB_URL_RE.findall(resp.text)))
    for url in urls:
        job_id_match = _JOB_ID_FROM_URL_RE.search(url)
        if not job_id_match:
            continue
        try:
            page = requests.get(url, timeout=30)
            page.raise_for_status()
        except requests.RequestException:
            continue
        jsonld_match = _JSONLD_RE.search(page.text)
        if not jsonld_match:
            continue
        try:
            posting = json.loads(jsonld_match.group(1))
        except json.JSONDecodeError:
            continue
        address = (posting.get("jobLocation") or {}).get("address") or {}
        country = address.get("addressCountry")
        country_name = country.get("name") if isinstance(country, dict) else country
        yield {
            "external_id": job_id_match.group(1),
            "title": clean_text(posting.get("title")),
            "source_url": url,
            "location_raw": clean_text(address.get("addressLocality")),
            "location_city": address.get("addressLocality"),
            "location_region": address.get("addressRegion"),
            "location_country": country_name,
            "employment_type": clean_text(posting.get("employmentType")),
            "posted_date": (posting.get("datePosted") or "")[:10] or None,
            "description_text": clean_description(posting.get("description")),
        }


def fetch_postings(employer: Employer) -> Iterator[dict[str, Any]]:
    host = employer.ats_config.get("host")
    if not host:
        return
    group_id = _group_id(host)
    postings = None
    if group_id:
        postings = _fetch_via_public_api(host, group_id)
    if postings is None:
        postings = _sitemap_postings(host)
    yield from postings
