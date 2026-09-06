"""research.md §5: shared post-ingest location normalization.

Adapters land location_raw (and any source-provided structured fields)
verbatim at capture time — never transforming inside the resource
itself (the dlt-pipeline research doc's "raw + view" lesson). This
pass fills location_city/region/country for rows a platform only
returned as freetext (e.g. Workday's locationsText), using the shared
`TARGET_CITIES` gazetteer (pipelines/common/target_cities.py — extend
the watchlist to a new city by adding it there, not here). A location
that genuinely can't be resolved is left null — visible via
location_raw, never dropped or guessed.
"""

import re

from pipelines.common.db import get_connection
from pipelines.common.target_cities import CITY_ALIASES, TARGET_CITIES

# Real captured location_raw strings routinely list a target city as one
# entry in a multi-city list ("New York, London", "Dubai, London, Paris,
# Hong Kong, Sydney, Toronto", "San Francisco, Dublin, Ireland, London, UK")
# - a plain \bword\b substring search matches those correctly, but also
# incorrectly matches a city name embedded in an unrelated street/place
# name in the same shape ("Lowestoft, London Road North" - confirmed live
# in Workday's own location facet data). jseek's own location resolver
# tokenizes before matching for exactly this reason (see
# core/location_resolve.py) - borrowing that principle without their full
# GeoNames machinery: split on common delimiters and require an
# INDIVIDUAL segment to equal the city name exactly, not just contain it.
_SPLIT_RE = re.compile(r",|;| - |\bor\b", re.IGNORECASE)


def _segments(location_raw: str) -> list[str]:
    return [s.strip().casefold() for s in _SPLIT_RE.split(location_raw) if s.strip()]


def normalize_location(location_raw: str | None) -> tuple[str | None, str | None, str | None]:
    """Returns (city, region, country) — or (None, None, None) if
    location_raw is empty or doesn't match any city in TARGET_CITIES."""
    if not location_raw:
        return (None, None, None)
    segments = _segments(location_raw)
    for segment in segments:
        key = CITY_ALIASES.get(segment, segment)
        if key in TARGET_CITIES:
            region, country = TARGET_CITIES[key]
            return (key.title(), region, country)
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
