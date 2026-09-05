"""research.md §5: shared post-ingest location normalization.

Adapters land location_raw (and any source-provided structured fields)
verbatim at capture time — never transforming inside the resource
itself (the dlt-pipeline research doc's "raw + view" lesson). This
pass fills location_city/region/country for rows a platform only
returned as freetext (e.g. Workday's locationsText), using a fixed
London/Dublin gazetteer. A location that genuinely can't be resolved
is left null — visible via location_raw, never dropped or guessed.
"""

import re

from pipelines.common.db import get_connection

_LONDON = re.compile(r"\blondon\b", re.IGNORECASE)
_DUBLIN = re.compile(r"\bdublin\b", re.IGNORECASE)


def normalize_location(location_raw: str | None) -> tuple[str | None, str | None, str | None]:
    """Returns (city, region, country) — or (None, None, None) if
    location_raw is empty or doesn't match the London/Dublin gazetteer."""
    if not location_raw:
        return (None, None, None)
    if _LONDON.search(location_raw):
        return ("London", "England", "United Kingdom")
    if _DUBLIN.search(location_raw):
        return ("Dublin", "Leinster", "Ireland")
    return (None, None, None)


def apply_location_normalization(employer_id: str) -> int:
    """Fills location_city/region/country for this employer's rows
    where location_city is still null. Returns the number of rows
    updated."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select id, location_raw from job_postings
             where employer_id = %s and location_city is null and location_raw is not null
            """,
            (employer_id,),
        )
        rows = cur.fetchall()
        updated = 0
        for posting_id, location_raw in rows:
            city, region, country = normalize_location(location_raw)
            if city is None:
                continue  # genuinely ambiguous — left null and visible, per the spec's edge case
            cur.execute(
                """
                update job_postings
                   set location_city = %s, location_region = %s, location_country = %s
                 where id = %s
                """,
                (city, region, country, posting_id),
            )
            updated += 1
        conn.commit()
    return updated
