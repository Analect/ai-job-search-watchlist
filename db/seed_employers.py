"""T013: seed `employers` from the user's 69-company shortlist.

Reads db/seed_data/jseek-shortlist.xlsx (the full ~7,038-row jseek
registry with a `short_list` column marked 'x' for the user's own
picks — per 20260904-shortlist-direct-api-coverage.md) and inserts one
row per shortlisted company into `employers`, matching data-model.md.

`collection_supported` is set true only for the 8 ATS types with
confirmed, live-tested direct-API access
(20260904-shortlist-direct-api-coverage.md) — sitemap/dom/api_sniffer/
nextdata/phenom/amazon/rss employers are seeded as
short_listed=true, collection_supported=false (FR-010): visible on the
watchlist, not yet actively collected.

Usage: python -m db.seed_employers  (requires JOB_SEARCH_PG_DSN in env
— see pipelines/common/db.py)
"""

import re
from pathlib import Path

import pandas as pd

from pipelines.common.db import get_connection

SHORTLIST_XLSX = Path(__file__).parent / "seed_data" / "jseek-shortlist.xlsx"

# The 8 ATS types with confirmed, live-tested direct-API coverage
# (20260904-shortlist-direct-api-coverage.md) — the only ones with a
# pipelines/adapters/<type>.py adapter in this repo.
AUTOMATED_ATS_TYPES = {
    "workday",
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "pinpoint",
    "oracle_hcm",
    "eightfold",
}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unknown"


def load_shortlist() -> pd.DataFrame:
    df = pd.read_excel(SHORTLIST_XLSX)
    df["short_list"] = df["short_list"].astype(str).str.strip().str.lower()
    shortlisted = df[df["short_list"] == "x"].copy()
    shortlisted["slug"] = shortlisted["company_name"].map(slugify)
    return shortlisted


def seed() -> int:
    shortlisted = load_shortlist()
    rows = [
        (
            row.slug,
            row.company_name,
            row.website if pd.notna(row.website) else None,
            row.industry if pd.notna(row.industry) else None,
            (
                str(row.employee_count_range)
                if pd.notna(row.employee_count_range)
                else None
            ),
            row.ats_type,
            row.ats_type in AUTOMATED_ATS_TYPES,
        )
        for row in shortlisted.itertuples()
    ]

    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            insert into employers
                (slug, name, website, industry, employee_count_range,
                 ats_type, short_listed, active, collection_supported)
            values (%s, %s, %s, %s, %s, %s, true, true, %s)
            on conflict (slug) do nothing
            """,
            rows,
        )
        conn.commit()
    return len(rows)


if __name__ == "__main__":
    n = seed()
    print(f"Seeded {n} shortlisted employers.")
