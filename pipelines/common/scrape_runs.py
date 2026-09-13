"""FR-008's per-employer health-signal helpers (ats-adapter.contract.md).

Every ATS adapter's dlt resource wraps its per-employer fetch in
start_scrape_run()/complete_scrape_run() so `scrape_runs` — not dlt's
own pipeline-level trace — is the source of truth for "did the most
recent collection attempt for THIS employer succeed" (research.md §4).
"""

from datetime import UTC, datetime
from uuid import UUID

from pipelines.common.db import get_connection


def start_scrape_run(employer_id: UUID, pipeline_run_id: str | None = None) -> UUID:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into scrape_runs (employer_id, pipeline_run_id, status)
            values (%s, %s, 'running')
            returning id
            """,
            (str(employer_id), pipeline_run_id),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
    return run_id


def complete_scrape_run(
    run_id: UUID,
    status: str,
    postings_found: int | None = None,
    postings_new: int | None = None,
    error_message: str | None = None,
) -> None:
    if status not in ("success", "failed", "partial"):
        raise ValueError(f"invalid scrape_runs.status: {status!r}")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update scrape_runs
               set status = %s,
                   completed_at = %s,
                   postings_found = %s,
                   postings_new = %s,
                   error_message = %s
             where id = %s
            """,
            (status, datetime.now(UTC), postings_found, postings_new, error_message, str(run_id)),
        )
        employer_id = _employer_id_for_run(cur, run_id)
        if status == "success":
            if postings_found and postings_found > 0:
                cur.execute(
                    """
                    update employers
                       set last_successful_run_at = now(),
                           consecutive_failures = 0,
                           consecutive_zero_postings = 0,
                           last_error = null
                     where id = %s
                    """,
                    (employer_id,),
                )
            else:
                cur.execute(
                    """
                    update employers
                       set last_successful_run_at = now(),
                           consecutive_failures = 0,
                           consecutive_zero_postings = consecutive_zero_postings + 1,
                           last_error = null
                     where id = %s
                    """,
                    (employer_id,),
                )
        else:
            cur.execute(
                """
                update employers
                   set consecutive_failures = consecutive_failures + 1,
                       last_error = %s
                 where id = %s
                """,
                (error_message, employer_id),
            )
        conn.commit()


def _employer_id_for_run(cur, run_id: UUID) -> str:
    cur.execute("select employer_id from scrape_runs where id = %s", (str(run_id),))
    return cur.fetchone()[0]
