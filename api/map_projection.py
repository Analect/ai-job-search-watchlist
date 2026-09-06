"""T049: the T048-validated TF-IDF (1-2 grams) -> UMAP (cosine) company
similarity projection, exposed for `GET /map/coordinates`
(job-search-api.contract.md).

Computed once and cached for the life of the process, not per request —
UMAP's fit over ~2,700 companies takes real time (confirmed live,
several seconds), and the underlying `jseek_companies`/
`jseek_company_descriptions` data itself only changes when
`db/refresh_jseek_reference.py` next runs (a periodic, not continuous,
refresh) — there's nothing to gain from recomputing this on every
request. A process restart (redeploy) is what picks up fresher jseek
data.
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from umap import UMAP

from pipelines.common.db import get_connection

_cache: list[dict] | None = None


def _compute_projection() -> list[dict]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select
                c.slug,
                c.name,
                i.name as industry,
                d.description,
                e.short_listed,
                (
                    select string_agg(distinct b.monitor_type, ', ')
                    from jseek_boards b
                    where b.company_slug = c.slug
                ) as ats_types
            from jseek_companies c
            join jseek_company_descriptions d on d.company_slug = c.slug and d.locale = 'en'
            join jseek_industries i on i.id = c.industry_id
            left join employers e on e.slug = c.slug
            where i.name in ('Technology', 'Financial Services', 'Professional Services')
              and d.description is not null and d.description != ''
            """
        )
        rows = cur.fetchall()

    descriptions = [r[3] for r in rows]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2, stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(descriptions)
    reducer = UMAP(n_components=2, metric="cosine", random_state=42)
    coords = reducer.fit_transform(tfidf_matrix)

    return [
        {
            "slug": row[0],
            "name": row[1],
            "industry": row[2],
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
            "short_listed": bool(row[4]) if row[4] is not None else False,
            "ats_types": row[5],
        }
        for i, row in enumerate(rows)
    ]


def get_projection(refresh: bool = False) -> list[dict]:
    global _cache
    if _cache is None or refresh:
        _cache = _compute_projection()
    return _cache
