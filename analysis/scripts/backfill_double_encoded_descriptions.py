"""Backfill doubly-encoded HTML descriptions in the descriptions table.

Finds every row where content contains &lt;tag&gt; patterns (doubly-encoded
HTML entities) and applies clean_description() to fix them in place.

Run by piping into the job-search-api pod, which has DB credentials and
the pipelines.common package available:

    NS=$(kubectl get ns -o name | grep dp-analect-ai-job-search-development | cut -d/ -f2)
    POD=$(kubectl get pod -n $NS -l app=job-search-api-development -o name | head -1 | cut -d/ -f2)
    kubectl exec -i -n $NS $POD -- python3 - < analysis/scripts/backfill_double_encoded_descriptions.py

Safe to re-run: clean_description() is idempotent — already-correct rows
pass through unchanged and are skipped by the content_hash check.
"""

import hashlib

from pipelines.common.db import get_connection
from pipelines.common.text_clean import clean_description

BATCH_SIZE = 100


def run() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from descriptions where content ~ '&lt;[a-zA-Z]'"
        )
        total = cur.fetchone()[0]

    if total == 0:
        print("No doubly-encoded descriptions found — nothing to do.")
        return

    print(f"Found {total} doubly-encoded descriptions. Starting backfill...")

    fixed = 0
    skipped = 0

    while True:
        # Always query from offset 0 — fixed rows drop out of the WHERE clause,
        # so advancing an offset would skip over rows that shifted up.
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select job_posting_id, locale, content
                  from descriptions
                 where content ~ '&lt;[a-zA-Z]'
                 order by job_posting_id, locale
                 limit %s
                """,
                (BATCH_SIZE,),
            )
            rows = cur.fetchall()

        if not rows:
            break

        for job_posting_id, locale, content in rows:
            cleaned = clean_description(content)
            if cleaned == content:
                # Detection fired but clean_description made no change — skip
                skipped += 1
                continue

            new_hash = hashlib.sha256(cleaned.encode()).hexdigest()
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    update descriptions
                       set content = %s, content_hash = %s
                     where job_posting_id = %s and locale = %s
                    """,
                    (cleaned, new_hash, job_posting_id, locale),
                )
                conn.commit()
            fixed += 1

        print(f"  progress: {fixed} fixed, {skipped} skipped")

    print(f"\nBackfill complete: {fixed} rows fixed, {skipped} rows skipped.")


if __name__ == "__main__":
    run()
