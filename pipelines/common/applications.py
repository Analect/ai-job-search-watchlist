"""017-enhanced-job-search: applications table CRUD and lifecycle.

Called by api/app.py's promoted and withdrawn event routes (T005) and
by the GET /applications + status-advance + generate-drafts routes
(T035/T036/T039).  Never called directly by pipelines.
"""

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
                   draft_generated_at, created_at, updated_at
              from applications
             where job_posting_id = %s
            """,
            (pid,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_all() -> list[dict]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select a.id, a.job_posting_id, a.status,
                   jp.title, e.name as employer_name,
                   a.resume_draft_mr_url, a.draft_generated_at,
                   a.created_at, a.updated_at
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
                   updated_at              = now()
             where job_posting_id = %s
            returning id, job_posting_id, status, resume_draft_branch,
                      resume_draft_mr_url, resume_draft_path,
                      cover_letter_draft_path, draft_generated_at,
                      created_at, updated_at
            """,
            (branch, mr_url, resume_path, cover_letter_path, generated_at, pid),
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


def get_draft_info(job_posting_id: UUID | str) -> dict | None:
    """Return draft fields if they're already set (idempotency check for T039)."""
    pid = str(job_posting_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select resume_draft_branch, resume_draft_mr_url,
                   resume_draft_path, cover_letter_draft_path,
                   draft_generated_at, status
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
    }


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "job_posting_id": row[1],
        "status": row[2],
        "resume_draft_mr_url": row[3],
        "draft_generated_at": row[4],
    }
