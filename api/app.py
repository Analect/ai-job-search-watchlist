"""job-search-api: the direct (non-assistant) path for FR-003, FR-011,
FR-012, FR-013, FR-014-017 (job-search-api.contract.md).

No auth logic lives here — same convention as
insurance-support-agent/agent/: the platform gateway in front of this
Component is what validates the caller's identity.

Reuses pipelines/common/db.py (not a separate api/db.py) as its
connection helper — the same DSN convention every adapter, the
enrichment pass, and mcp_server/server.py already use.
"""

from uuid import UUID

from fastapi import FastAPI, HTTPException, Query

from pipelines.common.db import get_connection
from pipelines.common.postings import get_job_detail, list_postings

app = FastAPI(title="job-search-api")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


def _db_ok() -> bool:
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("select 1")
            cur.fetchone()
        return True
    except Exception:
        return False


@app.get("/readyz")
def readyz() -> dict:
    return {"db": "ok" if _db_ok() else "unreachable"}


@app.get("/postings")
def get_postings(
    location: str | None = Query(default=None, pattern="^(london|dublin|other)$"),
    status: str | None = Query(default=None, pattern="^(open|closed)$"),
    review_state: str | None = Query(
        default=None,
        pattern="^(unreviewed|flagged_for_advancement|dismissed)$",
    ),
    query: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return list_postings(
        location=location,
        status=status,
        review_state=review_state,
        query=query,
        limit=limit,
        offset=offset,
    )


@app.get("/postings/{posting_id}")
def get_posting_detail(posting_id: UUID) -> dict:
    detail = get_job_detail(posting_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="posting not found")
    return detail
