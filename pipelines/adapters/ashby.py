"""Ashby adapter (20260904-shortlist-direct-api-coverage.md).

ats_config shape: {"token": "<company-token>"}
Structured address.postalAddress — preserved at capture time per
research.md §5 (never left to the shared normalization pass, since
the source already gives us structured fields; this is actually more
complete than jseek's own flatten-to-string fallback, kept as-is).

2026-09-05 review against jseek's real `core/monitors/ashby.py` found
further gaps beyond the structured-address handling: no retry/backoff
(http_retry.py existed but wasn't wired in), no `includeCompensation=true`
param, `isListed: false` (unlisted/draft) postings were never filtered
out, description preferred `descriptionPlain` only (jseek prefers the
richer `descriptionHtml`, falling back to plain), no text cleanup, and
`secondaryLocations` (additional office locations beyond the primary)
were dropped entirely.
"""

from collections.abc import Iterator
from typing import Any

from pipelines.common.http_retry import fetch_json_with_retry
from pipelines.common.text_clean import clean_description, clean_text
from pipelines.common.types import Employer


def fetch_postings(employer: Employer) -> Iterator[dict[str, Any]]:
    token = employer.ats_config.get("token")
    if not token:
        return
    data = fetch_json_with_retry(
        "GET",
        f"https://api.ashbyhq.com/posting-api/job-board/{token}",
        params={"includeCompensation": "true"},
    )
    for job in data.get("jobs", []):
        if not job.get("isListed", True):
            continue  # unlisted/draft postings the list endpoint still returns
        addr = ((job.get("address") or {}).get("postalAddress")) or {}
        locations = []
        if job.get("location"):
            locations.append(job["location"])
        for loc in job.get("secondaryLocations", []):
            name = loc if isinstance(loc, str) else (loc or {}).get("location")
            if name and name not in locations:
                locations.append(name)
        yield {
            "external_id": job["id"],
            "title": clean_text(job.get("title")),
            "source_url": job.get("jobUrl"),
            "location_raw": clean_text(", ".join(locations)) if locations else None,
            "location_city": addr.get("addressLocality"),
            "location_region": addr.get("addressRegion"),
            "location_country": addr.get("addressCountry"),
            "is_remote": job.get("isRemote")
            if job.get("isRemote") is not None
            else (job.get("workplaceType") == "Remote") or None,
            "employment_type": clean_text(job.get("employmentType")),
            "department": clean_text(job.get("department")),
            "posted_date": (job.get("publishedAt") or "")[:10] or None,
            "description_text": clean_description(
                job.get("descriptionHtml") or job.get("descriptionPlain")
            ),
        }
