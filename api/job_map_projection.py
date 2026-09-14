"""017-enhanced-job-search (T020): UMAP-over-embeddings 2D projection for
the Job Watch map (FR-019, research.md §5).

Mirrors api/map_projection.py's cache pattern exactly:
  - x/y coordinates computed once per process lifetime from
    job_postings.embedding (already populated by enrichment_pipeline).
  - promoted/reviewed/flagged/thumbs queried fresh per request —
    same freshness reasoning as short_listed on the employer map.
  - Warmed in api/app.py's lifespan startup handler alongside
    get_projection() to avoid a cold-start 504.

T061 (US17): JOB_MAP_UMAP_MIN_DIST env var controls UMAP clustering
tightness at deployment time (default "0.1" matches prior behaviour).
"""

import os

from umap import UMAP

from pipelines.common.db import get_connection

_cache: list[dict] | None = None


def _compute_job_projection() -> list[dict]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select jp.id, e.name, jp.title, jp.map_embedding
              from job_postings jp
              join employers e on e.id = jp.employer_id
             where jp.status = 'open'
               and jp.map_embedding is not null
            """
        )
        rows = cur.fetchall()

    if not rows:
        return []

    # psycopg2 returns the pgvector column as a string like '[0.1,0.2,...]'
    import numpy as np

    embeddings = []
    valid_rows = []
    for row in rows:
        raw = row[3]
        if raw is None:
            continue
        vec = [float(x) for x in raw.strip("[]").split(",")]
        embeddings.append(vec)
        valid_rows.append(row)

    if len(embeddings) < 2:
        return []

    matrix = np.array(embeddings)
    try:
        min_dist = float(os.environ.get("JOB_MAP_UMAP_MIN_DIST", "0.1"))
    except (ValueError, TypeError):
        min_dist = 0.1
    reducer = UMAP(n_components=2, metric="cosine", random_state=42, min_dist=min_dist)
    coords = reducer.fit_transform(matrix)

    return [
        {
            "id": str(row[0]),
            "employer_name": row[1],
            "title": row[2],
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
        }
        for i, row in enumerate(valid_rows)
    ]


def _fetch_fresh_review_states() -> dict[str, dict]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "select id::text, promoted, reviewed, flagged, thumbs from job_postings"
        )
        return {
            r[0]: {"promoted": r[1], "reviewed": r[2], "flagged": r[3], "thumbs": r[4]}
            for r in cur.fetchall()
        }


def get_job_projection(refresh: bool = False) -> list[dict]:
    global _cache
    if _cache is None or refresh:
        _cache = _compute_job_projection()

    states = _fetch_fresh_review_states()
    result = []
    for job in _cache:
        state = states.get(job["id"], {})
        result.append(
            {
                **job,
                "promoted": state.get("promoted", False),
                "reviewed": state.get("reviewed", False),
                "flagged": state.get("flagged", False),
                "thumbs": state.get("thumbs"),
            }
        )
    return result
