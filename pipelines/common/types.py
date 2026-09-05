"""Shared types for ATS adapters (ats-adapter.contract.md)."""

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class Employer:
    id: str
    slug: str
    name: str
    ats_type: str
    ats_config: dict[str, Any]


def parse_date(value: str | None) -> date | None:
    """Adapters return posted_date as an ISO date string (or None); dlt
    infers a Python str as varchar regardless of content, which then fails
    a typed INSERT/UPDATE against a real Postgres `date` column the same
    way it does for uuid columns. Every *_pipeline.py resource must pass
    dlt a real date object for date-typed columns, not a string.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
