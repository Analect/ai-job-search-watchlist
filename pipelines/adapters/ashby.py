"""Ashby adapter (20260904-shortlist-direct-api-coverage.md).

ats_config shape: {"token": "<company-token>"}
Structured address.postalAddress — preserved at capture time per
research.md §5 (never left to the shared normalization pass, since
the source already gives us structured fields).
"""

from collections.abc import Iterator
from typing import Any

import requests

from pipelines.common.types import Employer


def fetch_postings(employer: Employer) -> Iterator[dict[str, Any]]:
    token = employer.ats_config.get("token")
    if not token:
        return
    resp = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{token}",
        timeout=30,
    )
    resp.raise_for_status()
    for job in resp.json().get("jobs", []):
        addr = ((job.get("address") or {}).get("postalAddress")) or {}
        yield {
            "external_id": job["id"],
            "title": job.get("title"),
            "source_url": job.get("jobUrl"),
            "location_raw": job.get("location"),
            "location_city": addr.get("addressLocality"),
            "location_region": addr.get("addressRegion"),
            "location_country": addr.get("addressCountry"),
            "is_remote": job.get("isRemote"),
            "employment_type": job.get("employmentType"),
            "department": job.get("department"),
            "posted_date": (job.get("publishedAt") or "")[:10] or None,
            "description_text": job.get("descriptionPlain"),
        }
