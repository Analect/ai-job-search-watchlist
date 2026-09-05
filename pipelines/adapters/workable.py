"""Workable adapter (20260904-shortlist-direct-api-coverage.md).

ats_config shape: {"token": "<company-token>"}
The list endpoint doesn't inline description text (unlike Greenhouse's
`content=true`) — one per-job detail fetch is needed. Only 2 shortlist
companies use this platform with modest posting counts, so the N+1
cost is acceptable here (contrast with Greenhouse, where content=true
avoids it for the platform with the largest company count).
"""

from collections.abc import Iterator
from typing import Any

import requests

from pipelines.common.types import Employer


def fetch_postings(employer: Employer) -> Iterator[dict[str, Any]]:
    token = employer.ats_config.get("token")
    if not token:
        return
    resp = requests.post(
        f"https://apply.workable.com/api/v1/accounts/{token}/jobs",
        headers={"Content-Type": "application/json"},
        json={},
        timeout=30,
    )
    resp.raise_for_status()
    for job in resp.json().get("results", []):
        loc = job.get("location") or {}
        description_text = None
        try:
            detail = requests.get(
                f"https://apply.workable.com/api/v1/accounts/{token}/jobs/{job['shortcode']}",
                timeout=30,
            )
            if detail.ok:
                description_text = detail.json().get("description")
        except requests.RequestException:
            pass
        yield {
            "external_id": str(job["id"]),
            "title": job.get("title"),
            "source_url": f"https://apply.workable.com/{token}/j/{job['shortcode']}/",
            "location_raw": ", ".join(
                filter(None, [loc.get("city"), loc.get("region"), loc.get("country")])
            ),
            "location_city": loc.get("city"),
            "location_region": loc.get("region"),
            "location_country": loc.get("country"),
            "is_remote": job.get("remote"),
            "employment_type": job.get("type"),
            "department": ", ".join(job.get("department") or []) or None,
            "posted_date": (job.get("published") or "")[:10] or None,
            "description_text": description_text,
        }
