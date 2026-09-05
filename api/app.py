"""job-search-api: the direct (non-assistant) path for FR-003, FR-011,
FR-012, FR-013, FR-014-017 (job-search-api.contract.md).

No auth logic lives here — same convention as
insurance-support-agent/agent/: the platform gateway in front of this
Component is what validates the caller's identity.

Reuses pipelines/common/db.py (not a separate api/db.py) as its
connection helper — the same DSN convention every adapter, the
enrichment pass, and mcp_server/server.py already use.
"""

from fastapi import FastAPI

from pipelines.common.db import get_connection

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
