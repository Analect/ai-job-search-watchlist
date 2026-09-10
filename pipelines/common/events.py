"""research.md §11 / job-search-api.contract.md / mcp-server-tools.contract.md:
the SINGLE mark-for-advancement write path.

Both api/app.py's POST /postings/{id}/events (source='user') and
mcp_server/server.py's mark_for_advancement tool (source='assistant')
call this function — never a separate insert — so the "one consistent
record, not two" invariant holds structurally, not by convention.
"""

from uuid import UUID

from pipelines.common.db import get_connection

# New vocabulary (017-enhanced-job-search, data-model.md).
# 'flagged_for_advancement' and 'dismissed' are no longer accepted for
# new writes; they remain valid in already-written historical rows.
VALID_EVENT_TYPES = {
    "captured",
    "seen",
    "reviewed",
    "flag_on",
    "flag_off",
    "promoted",
    "withdrawn",
    "thumbs_up",
    "thumbs_down",
    "thumbs_cleared",
    "comment_updated",
    "applied",
    "interviewing",
    "offered",
    "rejected",
    "archived",
}

# Map from event_type to the SQL column + value to write on job_postings
# in the same transaction.  'promoted' and 'withdrawn' are intentionally
# absent — they are routed through applications.py (T004/T005) which also
# touches the applications table.
_POSTING_COLUMN_UPDATE: dict[str, str] = {
    "reviewed":        "reviewed = true",
    "flag_on":         "flagged = true",
    "flag_off":        "flagged = false",
    "thumbs_up":       "thumbs = 'up'",
    "thumbs_down":     "thumbs = 'down'",
    "thumbs_cleared":  "thumbs = null",
    # comment_updated is special — the new text comes from 'note'; handled inline.
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

        # Simultaneously update the denormalized state column on job_postings
        # so the read path never has to derive state by folding event history.
        if event_type in _POSTING_COLUMN_UPDATE:
            cur.execute(
                f"update job_postings set {_POSTING_COLUMN_UPDATE[event_type]} where id = %s",
                (str(job_posting_id),),
            )
        elif event_type == "comment_updated":
            cur.execute(
                "update job_postings set comment = %s where id = %s",
                (note, str(job_posting_id)),
            )

        conn.commit()
    return {"event_type": row[0], "source": row[1], "note": row[2], "created_at": row[3]}


def latest_review_state(job_posting_id: UUID | str) -> str:
    """Legacy read helper — still used by some tests.  New code should read
    the boolean columns on job_postings directly; this scans job_events and
    is kept for backward-compat only."""
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
