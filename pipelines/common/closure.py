"""research.md §6 / ats-adapter.contract.md: success-gated closure.

A posting is inferred closed only after a run whose OWN scrape_runs
row succeeded completes without that posting's external_id appearing
— never as a side effect of a failed or partial run (SC-006). Call
apply_closure() once per employer, immediately after that employer's
ingest step in the same pipeline run, passing the external_ids the
run actually saw.
"""

from uuid import UUID

from pipelines.common.db import get_connection


def apply_closure(employer_id: UUID, external_ids_seen: list[str], run_status: str) -> None:
    if run_status != "success":
        # SC-006: a failed/partial run must never close postings it
        # never got far enough to actually re-observe.
        return

    with get_connection() as conn, conn.cursor() as cur:
        if external_ids_seen:
            cur.execute(
                """
                update job_postings
                   set missing_count = missing_count + 1,
                       status = case when missing_count + 1 >= 1 then 'closed' else status end
                 where employer_id = %s
                   and status = 'open'
                   and external_id != all(%s)
                """,
                (str(employer_id), external_ids_seen),
            )
            # Reopen a posting re-seen after a prior run missed it (e.g. one
            # transient API blip) — found via T039 verification: without
            # this, a posting that vanishes for exactly one run stays
            # 'closed' forever even though every later run keeps seeing it.
            cur.execute(
                """
                update job_postings
                   set missing_count = 0,
                       status = 'open'
                 where employer_id = %s
                   and external_id = any(%s)
                   and status = 'closed'
                """,
                (str(employer_id), external_ids_seen),
            )
        else:
            # An employer whose current listing is genuinely empty —
            # every previously-open posting is closed.
            cur.execute(
                """
                update job_postings
                   set missing_count = missing_count + 1,
                       status = 'closed'
                 where employer_id = %s
                   and status = 'open'
                """,
                (str(employer_id),),
            )
        conn.commit()
