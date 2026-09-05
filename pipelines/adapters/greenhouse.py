"""Greenhouse adapter (20260904-shortlist-direct-api-coverage.md).

ats_config shape: {"token": "<company-token>"}
Endpoint: boards-api.greenhouse.io (NOT job-boards.greenhouse.io, which
jseek's own board_url stores but 404s for this API).

Retry policy, 404-as-BoardGoneError, and description/text cleanup are
ported from jseek's own `core/monitors/greenhouse.py` — a 2026-09-05
review of that file (colophon-group/jobseek) against this adapter found
three real gaps: no retry/backoff (http_retry.py existed but was never
wired in here), `department` silently always null (never extracted from
the API response despite the pipeline expecting it), and no WYSIWYG
description cleanup. All three fixed here.
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
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        params={"content": "true"},
    )
    for job in data.get("jobs", []):
        departments = [d.get("name") for d in job.get("departments", []) if d.get("name")]
        yield {
            "external_id": str(job["id"]),
            "title": clean_text(job.get("title")),
            "source_url": job["absolute_url"],
            "location_raw": clean_text((job.get("location") or {}).get("name")),
            "department": ", ".join(departments) or None,
            "posted_date": (job.get("first_published") or "")[:10] or None,
            "description_text": clean_description(job.get("content")),
        }
