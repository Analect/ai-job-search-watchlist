"""Lever adapter — ported from jseek's `core/monitors/lever.py` (MIT),
per research.md §9. Real logic worth keeping, found only by reading
their code (not discoverable from a single curl test): pagination via
`limit`/`skip` (default single-page curl tests miss this for
higher-volume boards), and descriptions assembled from THREE fields
(`description` + `lists` requirements/responsibilities sections +
`additional` EEO text), not just `descriptionPlain` alone.

ats_config shape: {"token": "<company-token>"}
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from pipelines.common.http_retry import BoardGoneError, fetch_json_with_retry
from pipelines.common.text_clean import clean_description, clean_text
from pipelines.common.types import Employer

BATCH_SIZE = 100
_API_HEADERS = {"Accept": "application/json"}


def _api_url(token: str) -> str:
    return f"https://api.lever.co/v0/postings/{token}"


def _build_description(posting: dict) -> str | None:
    parts: list[str] = []
    if posting.get("description"):
        parts.append(posting["description"])
    for item in posting.get("lists", []):
        text, content = item.get("text", ""), item.get("content", "")
        if text or content:
            parts.append(f"<h3>{text}</h3><ul>{content}</ul>")
    if posting.get("additional"):
        parts.append(posting["additional"])
    return clean_description("\n".join(parts)) if parts else None


def fetch_postings(employer: Employer) -> Iterator[dict[str, Any]]:
    token = employer.ats_config.get("token")
    if not token:
        return
    url = _api_url(token)
    skip = 0
    while True:
        try:
            batch = fetch_json_with_retry(
                "GET", url, params={"limit": BATCH_SIZE, "skip": skip}, headers=_API_HEADERS
            )
        except BoardGoneError:
            if skip == 0:
                return  # board removed — no postings, not an error for this run
            raise

        for job in batch:
            if not job.get("hostedUrl"):
                continue
            categories = job.get("categories", {})
            locations = categories.get("allLocations") or (
                [categories["location"]] if categories.get("location") else []
            )
            created_at = job.get("createdAt")
            posted_date = None
            if created_at:
                posted_date = datetime.fromtimestamp(created_at / 1000, tz=UTC).date().isoformat()
            yield {
                "external_id": job["id"],
                "title": clean_text(job.get("text")),
                "source_url": job["hostedUrl"],
                "location_raw": clean_text(", ".join(locations)) if locations else None,
                "employment_type": clean_text(categories.get("commitment")),
                "department": clean_text(categories.get("department")),
                # jseek's own DiscoveredJob captures this as job_location_type
                # rather than a boolean, but our schema only has is_remote —
                # 'remote' is the only workplaceType value that maps cleanly;
                # 'hybrid'/'onsite' are deliberately left None, not False,
                # since a posting listing a physical office isn't necessarily
                # confirmed non-remote-eligible.
                "is_remote": (job.get("workplaceType") == "remote") or None,
                "posted_date": posted_date,
                "description_text": _build_description(job),
            }

        if len(batch) < BATCH_SIZE:
            break
        skip += BATCH_SIZE
