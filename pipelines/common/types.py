"""Shared types for ATS adapters (ats-adapter.contract.md)."""

from dataclasses import dataclass
from typing import Any


@dataclass
class Employer:
    id: str
    slug: str
    name: str
    ats_type: str
    ats_config: dict[str, Any]
