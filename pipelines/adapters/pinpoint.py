"""Pinpoint adapter, ported from jseek's `core/monitors/pinpoint.py` (MIT).

ats_config shape: {"slug": "<company-subdomain>"} (e.g. "cinven" for
cinven.pinpointhq.com).

Lessons carried over from jseek's real code:
- Single request, no pagination (`postings.json` returns everything).
- Description is a compound HTML build: `description` +
  `key_responsibilities` (with header) + `skills_knowledge_expertise`
  (with header) + `benefits` (with header) - not just one field.
- `deadline_at` is the closest available date field (Pinpoint's API
  has no explicit "posted" timestamp in the list response).
"""

from collections.abc import Iterator
from typing import Any

from pipelines.common.http_retry import fetch_json_with_retry
from pipelines.common.text_clean import clean_description, clean_text
from pipelines.common.types import Employer


def _build_description(posting: dict) -> str | None:
    parts: list[str] = []
    for key, header_key in (
        ("description", None),
        ("key_responsibilities", "key_responsibilities_header"),
        ("skills_knowledge_expertise", "skills_knowledge_expertise_header"),
        ("benefits", "benefits_header"),
    ):
        text = posting.get(key)
        if not text or not isinstance(text, str):
            continue
        header = posting.get(header_key) if header_key else None
        parts.append(f"<h3>{header}</h3>\n{text}" if header else text)
    return clean_description("\n".join(parts)) if parts else None


def _build_location(posting: dict) -> str | None:
    loc = posting.get("location")
    if not isinstance(loc, dict):
        return None
    name = loc.get("name")
    if isinstance(name, str) and name:
        return clean_text(name)
    parts = [p for p in (loc.get("city"), loc.get("province")) if p]
    return clean_text(", ".join(parts)) if parts else None


def fetch_postings(employer: Employer) -> Iterator[dict[str, Any]]:
    slug = employer.ats_config.get("slug")
    if not slug:
        return
    data = fetch_json_with_retry(
        "GET",
        f"https://{slug}.pinpointhq.com/postings.json",
    )
    for posting in data.get("data", []):
        url = posting.get("url")
        if not url:
            continue
        job_obj = posting.get("job") if isinstance(posting.get("job"), dict) else {}
        department = None
        if isinstance(job_obj.get("department"), dict):
            department = job_obj["department"].get("name")
        yield {
            "external_id": str(posting.get("id") or url),
            "title": clean_text(posting.get("title")),
            "source_url": url,
            "location_raw": _build_location(posting),
            "department": clean_text(department),
            "employment_type": clean_text(
                posting.get("employment_type") or posting.get("employment_type_text")
            ),
            "is_remote": (posting.get("workplace_type") == "remote") or None,
            "posted_date": (posting.get("deadline_at") or "")[:10] or None,
            "description_text": _build_description(posting),
        }
