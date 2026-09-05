"""research.md §11 / job-search-api.contract.md / mcp-server-tools.contract.md:
the SINGLE mark-for-advancement write path.

Both api/app.py's POST /postings/{id}/events (source='user') and
mcp_server/server.py's mark_for_advancement tool (source='assistant')
call this function — never a separate insert — so FR-019's "one
consistent record, not two" holds structurally, not by convention
(closes /speckit.analyze finding H1).
"""

from uuid import UUID

from pipelines.common.db import get_connection

VALID_EVENT_TYPES = {
    "captured",
    "seen",
    "flagged_for_advancement",
    "dismissed",
    "applied",
    "interviewing",
    "offered",
    "rejected",
    "withdrawn",
    "archived",
}


def mark_for_advancement(
    job_posting_id: UUID | str,
    event_type: str,
    source: str,
    note: str | None = None,
) -> dict:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"invalid event_type: {event_type!r}")
    if source not in ("user", "assistant"):
        raise ValueError(f"invalid source: {source!r}")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into job_events (job_posting_id, event_type, source, note)
            values (%s, %s, %s, %s)
            returning event_type, source, note, created_at
            """,
            (str(job_posting_id), event_type, source, note),
        )
        row = cur.fetchone()
        conn.commit()
    return {"event_type": row[0], "source": row[1], "note": row[2], "created_at": row[3]}


def latest_review_state(job_posting_id: UUID | str) -> str:
    """The 'at a glance' review state (FR-013) — always derived from
    job_events, never a stored column that can drift."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select event_type from job_events
             where job_posting_id = %s
             order by created_at desc
             limit 1
            """,
            (str(job_posting_id),),
        )
        row = cur.fetchone()
    return row[0] if row else "unreviewed"
