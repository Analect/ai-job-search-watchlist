"""Greenhouse adapter (20260904-shortlist-direct-api-coverage.md).

ats_config shape: {"token": "<company-token>"}
Endpoint: boards-api.greenhouse.io (NOT job-boards.greenhouse.io, which
jseek's own board_url stores but 404s for this API).
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
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        params={"content": "true"},
        timeout=30,
    )
    resp.raise_for_status()
    for job in resp.json().get("jobs", []):
        yield {
            "external_id": str(job["id"]),
            "title": job["title"],
            "source_url": job["absolute_url"],
            "location_raw": (job.get("location") or {}).get("name"),
            "posted_date": (job.get("first_published") or "")[:10] or None,
            "description_text": job.get("content"),
        }
