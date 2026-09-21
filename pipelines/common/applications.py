"""017-enhanced-job-search: applications table CRUD and lifecycle.

Called by api/app.py's promoted and withdrawn event routes (T005) and
by the GET /applications + status-advance + generate-drafts routes
(T035/T036/T039).  Never called directly by pipelines.
"""

import json
from uuid import UUID

from pipelines.common.db import get_connection


class AlreadyActiveError(Exception):
    """Raised when create_or_reactivate is called on an already-promoted posting."""


def create_or_reactivate(job_posting_id: UUID | str) -> dict:
    """Insert a new applications row (status='promoted') for this posting,
    or if a withdrawn row already exists, set it back to 'promoted'.

    Raises AlreadyActiveError if the posting already has an active
    application (status in promoted|drafting|submitted) — re-promoting an
    active posting is a user error, not a no-op.
    """
    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, status from applications where job_posting_id = %s",
            (pid,),
        )
        existing = cur.fetchone()
        if existing:
            app_id, status = existing
            if status == "withdrawn":
                cur.execute(
                    """
                    update applications
                       set status = 'promoted', updated_at = now()
                     where id = %s
                    returning id, job_posting_id, status, resume_draft_mr_url,
                              draft_generated_at, created_at, updated_at
                    """,
                    (app_id,),
                )
            else:
                raise AlreadyActiveError(
                    f"posting {pid} already has an active application (status={status!r})"
                )
        else:
            cur.execute(
                """
                insert into applications (job_posting_id, status)
                values (%s, 'promoted')
                returning id, job_posting_id, status, resume_draft_mr_url,
                          draft_generated_at, created_at, updated_at
                """,
                (pid,),
            )
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


def withdraw(job_posting_id: UUID | str) -> dict:
    """Set the application's status to 'withdrawn'.

    404 (returns None) if no applications row exists for this posting.
    422 (raises ValueError) if job_postings.promoted is already false —
    the route layer checks this using the posting row it already loaded,
    so we don't re-check here.
    """
    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update applications
               set status = 'withdrawn', updated_at = now()
             where job_posting_id = %s
            returning id, job_posting_id, status, resume_draft_mr_url,
                      draft_generated_at, created_at, updated_at
            """,
            (pid,),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None
        conn.commit()
    return _row_to_dict(row)


def get(job_posting_id: UUID | str) -> dict | None:
    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select id, job_posting_id, status, resume_draft_mr_url,
                   draft_generated_at, created_at, updated_at,
                   application_notes, draft_model_id, draft_error
              from applications
             where job_posting_id = %s
            """,
            (pid,),
        )
        row = cur.fetchone()
    return _row_to_dict_extended(row) if row else None


def update_notes(job_posting_id: UUID | str, notes: str | None) -> dict | None:
    """Write application_notes for the given posting.

    Returns the updated row dict, or None if no applications row exists.
    """
    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update applications
               set application_notes = %s,
                   updated_at = now()
             where job_posting_id = %s
            returning id, job_posting_id, status, resume_draft_mr_url,
                      draft_generated_at, created_at, updated_at,
                      application_notes, draft_model_id, draft_error
            """,
            (notes, pid),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None
        conn.commit()
    return _row_to_dict_extended(row)


def list_all() -> list[dict]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select a.id, a.job_posting_id, a.status,
                   jp.title, e.name as employer_name,
                   a.resume_draft_mr_url, a.draft_generated_at,
                   a.created_at, a.updated_at,
                   a.application_notes, a.draft_model_id, a.draft_error,
                   a.draft_trace_id
              from applications a
              join job_postings jp on jp.id = a.job_posting_id
              join employers e on e.id = jp.employer_id
             order by a.created_at desc
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "job_posting_id": r[1],
            "status": r[2],
            "title": r[3],
            "employer_name": r[4],
            "resume_draft_mr_url": r[5],
            "draft_generated_at": r[6],
            "application_notes": r[9],
            "draft_model_id": r[10],
            "draft_error": r[11],
            "draft_trace_id": r[12],
        }
        for r in rows
    ]


_VALID_FORWARD_TRANSITIONS = {
    "promoted": "drafting",
    "drafting": "submitted",
}


def advance_status(job_posting_id: UUID | str, new_status: str) -> dict:
    """Advance applications.status along the forward-only path
    promoted -> drafting -> submitted.

    Returns None if no row exists (route layer raises 404).
    Raises ValueError on an invalid transition (route layer raises 422).
    'withdrawn' is explicitly rejected here — use applications.withdraw().
    """
    if new_status == "withdrawn":
        raise ValueError("use the withdrawn event endpoint to withdraw an application")

    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, status from applications where job_posting_id = %s",
            (pid,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        app_id, current_status = row
        if _VALID_FORWARD_TRANSITIONS.get(current_status) != new_status:
            raise ValueError(
                f"cannot advance from {current_status!r} to {new_status!r}"
            )

        cur.execute(
            """
            update applications
               set status = %s, updated_at = now()
             where id = %s
            returning id, job_posting_id, status, resume_draft_mr_url,
                      draft_generated_at, created_at, updated_at
            """,
            (new_status, app_id),
        )
        updated = cur.fetchone()
        conn.commit()
    return _row_to_dict(updated)


def persist_draft_info(
    job_posting_id: UUID | str,
    *,
    branch: str,
    mr_url: str,
    resume_path: str,
    cover_letter_path: str,
    generated_at: str,
    model_id: str | None = None,
    trace_id: str | None = None,
    draft_trace: dict | None = None,
) -> dict:
    """Persist resume-draft metadata on the applications row after a
    successful generate-drafts call (T039). Also advances status to
    'drafting'. Returns None if no row exists."""
    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update applications
               set status                  = 'drafting',
                   resume_draft_branch     = %s,
                   resume_draft_mr_url     = %s,
                   resume_draft_path       = %s,
                   cover_letter_draft_path = %s,
                   draft_generated_at      = %s,
                   draft_model_id          = %s,
                   draft_trace_id          = %s,
                   draft_trace             = %s::jsonb,
                   draft_error             = null,
                   updated_at              = now()
             where job_posting_id = %s
            returning id, job_posting_id, status, resume_draft_branch,
                      resume_draft_mr_url, resume_draft_path,
                      cover_letter_draft_path, draft_generated_at,
                      created_at, updated_at
            """,
            (branch, mr_url, resume_path, cover_letter_path, generated_at, model_id, trace_id,
             json.dumps(draft_trace) if draft_trace else None, pid),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None
        conn.commit()
    return {
        "id": row[0],
        "job_posting_id": row[1],
        "status": row[2],
        "resume_draft_branch": row[3],
        "resume_draft_mr_url": row[4],
        "resume_draft_path": row[5],
        "cover_letter_draft_path": row[6],
        "draft_generated_at": row[7],
    }


def set_draft_pending(job_posting_id: UUID | str) -> dict | None:
    """Mark draft generation as in-progress: status='drafting', clear all
    draft fields and any previous error. Returns None if no row exists."""
    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update applications
               set status                  = 'drafting',
                   resume_draft_branch     = null,
                   resume_draft_mr_url     = null,
                   resume_draft_path       = null,
                   cover_letter_draft_path = null,
                   draft_generated_at      = null,
                   draft_model_id          = null,
                   draft_trace_id          = null,
                   draft_error             = null,
                   updated_at              = now()
             where job_posting_id = %s
            returning id, job_posting_id, status, resume_draft_mr_url,
                      draft_generated_at, created_at, updated_at
            """,
            (pid,),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None
        conn.commit()
    return _row_to_dict(row)


def set_draft_failed(job_posting_id: UUID | str, error: str) -> None:
    """Record draft generation failure: reset status='promoted', store error."""
    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update applications
               set status      = 'promoted',
                   draft_error = %s,
                   updated_at  = now()
             where job_posting_id = %s
            """,
            (error, pid),
        )
        conn.commit()


def get_draft_status(job_posting_id: UUID | str) -> dict | None:
    """Return current async draft generation state for the poll endpoint.

    Returns None if no applications row exists.
    Returns one of:
      {"status": "pending"}
      {"status": "complete", ...draft fields}
      {"status": "failed", "error": "..."}
      {"status": "idle"}
    """
    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select status, resume_draft_branch, resume_draft_mr_url,
                   resume_draft_path, cover_letter_draft_path,
                   draft_generated_at, draft_error, draft_model_id, draft_trace_id
              from applications
             where job_posting_id = %s
            """,
            (pid,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    status, branch, mr_url, resume_path, cl_path, generated_at, draft_error, model_id, trace_id = row
    if status == "drafting" and mr_url is not None:
        return {
            "status": "complete",
            "resume_draft_branch": branch,
            "resume_draft_mr_url": mr_url,
            "resume_draft_path": resume_path,
            "cover_letter_draft_path": cl_path,
            "draft_generated_at": generated_at.isoformat() if generated_at else None,
            "draft_model_id": model_id,
            "draft_trace_id": trace_id,
        }
    if status == "drafting":
        return {"status": "pending"}
    if draft_error is not None:
        return {"status": "failed", "error": draft_error}
    return {"status": "idle"}


def get_draft_info(job_posting_id: UUID | str) -> dict | None:
    """Return draft fields if they're already set (idempotency check for T039)."""
    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select resume_draft_branch, resume_draft_mr_url,
                   resume_draft_path, cover_letter_draft_path,
                   draft_generated_at, status, draft_trace_id, draft_trace
              from applications
             where job_posting_id = %s
               and resume_draft_mr_url is not null
            """,
            (pid,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "resume_draft_branch": row[0],
        "resume_draft_mr_url": row[1],
        "resume_draft_path": row[2],
        "cover_letter_draft_path": row[3],
        "draft_generated_at": row[4],
        "status": row[5],
        "draft_trace_id": row[6],
        "draft_trace": row[7],
    }


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "job_posting_id": row[1],
        "status": row[2],
        "resume_draft_mr_url": row[3],
        "draft_generated_at": row[4],
    }


def _row_to_dict_extended(row) -> dict:
    """For queries that include application_notes, draft_model_id, draft_error
    as columns 7/8/9 (0-indexed)."""
    return {
        "id": row[0],
        "job_posting_id": row[1],
        "status": row[2],
        "resume_draft_mr_url": row[3],
        "draft_generated_at": row[4],
        "application_notes": row[7] if len(row) > 7 else None,
        "draft_model_id": row[8] if len(row) > 8 else None,
        "draft_error": row[9] if len(row) > 9 else None,
    }
