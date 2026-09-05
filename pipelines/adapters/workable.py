"""Workable adapter (20260904-shortlist-direct-api-coverage.md).

ats_config shape: {"token": "<company-token>"}
The list endpoint doesn't inline description text (unlike Greenhouse's
`content=true`) — one per-job detail fetch is needed. Only 2 shortlist
companies use this platform with modest posting counts, so the N+1
cost is acceptable here (contrast with Greenhouse, where content=true
avoids it for the platform with the largest company count).

2026-09-05 review against jseek's real `core/monitors/workable.py`:
their monitor is deliberately URL-discovery-only (`register(...,
rich=False)`) — description fetching is a SEPARATE scraper on a
slower schedule, because at jseek's scale (crawling thousands of
companies) a per-job detail fetch on every frequent poll would be
prohibitively expensive. That two-phase split doesn't apply here (2
employers, modest posting counts) so it's deliberately not replicated
— but their list endpoint has moved to v3 (POST .../api/v3/...,
not v1), which this adapter was still using.
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
        "POST",
        f"https://apply.workable.com/api/v3/accounts/{token}/jobs",
        json_body={"query": "", "location": [], "department": [], "worktype": []},
    )
    for job in data.get("results", []):
        loc = job.get("location") or {}
        description_text = None
        try:
            detail = fetch_json_with_retry(
                "GET",
                f"https://apply.workable.com/api/v1/accounts/{token}/jobs/{job['shortcode']}",
                retries=1,  # best-effort - a missing description shouldn't fail the posting
                raise_on_404=False,
            )
            description_text = clean_description(detail.get("description"))
        except Exception:
            pass
        yield {
            "external_id": str(job["id"]),
            "title": clean_text(job.get("title")),
            "source_url": f"https://apply.workable.com/{token}/j/{job['shortcode']}/",
            "location_raw": clean_text(
                ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
            ),
            "location_city": loc.get("city"),
            "location_region": loc.get("region"),
            "location_country": loc.get("country"),
            "is_remote": job.get("remote"),
            "employment_type": clean_text(job.get("type")),
            "department": clean_text(", ".join(job.get("department") or []) or None),
            "posted_date": (job.get("published") or "")[:10] or None,
            "description_text": description_text,
        }
