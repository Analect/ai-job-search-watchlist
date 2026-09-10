"""017-enhanced-job-search (T023): nearest-employer lookup for the
Employer Watch Watchlist tab's 'Similar' action (FR-017).

Finds the closest N companies by Euclidean distance over the UMAP x/y
coordinates already cached in api/map_projection.py — the same
clustering geometry used to place dots on the employer map, so 'similar'
is consistent with visual proximity, not a separate distance measure.
"""

import math

from api.map_projection import get_projection


def find_similar_employers(slug: str, limit: int = 5) -> dict:
    companies = get_projection()
    target = next((c for c in companies if c["slug"] == slug), None)
    if target is None:
        return {"results": [], "message": f"company {slug!r} not found in map"}

    tx, ty = target["x"], target["y"]
    scored = []
    for c in companies:
        if c["slug"] == slug:
            continue
        dist = math.sqrt((c["x"] - tx) ** 2 + (c["y"] - ty) ** 2)
        scored.append((dist, c))

    scored.sort(key=lambda t: t[0])
    return {
        "results": [
            {
                "slug": c["slug"],
                "name": c["name"],
                "industry": c["industry"],
                "short_listed": c.get("short_listed", False),
                "distance": round(dist, 4),
            }
            for dist, c in scored[:limit]
        ]
    }
