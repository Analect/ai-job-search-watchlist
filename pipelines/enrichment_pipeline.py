"""T042: combined enrichment pass - embeddings (T040) + key_terms
(T041) - over open postings needing enrichment (enrich_version null or
older than CURRENT_ENRICH_VERSION).

Plain script, not dlt-wrapped: unlike the 8 ATS adapters, this job
reads/updates rows already in job_postings via direct Bedrock calls and
a TF-IDF pass — it never fetches-and-merges from an external paginated
API, so dlt's resource/merge abstraction doesn't fit the same way it
does for ingest (see 20260906-phase4-enrichment-and-similarity.md).
"""

from pipelines.common.db import get_connection
from pipelines.enrichment.embeddings import embed_postings
from pipelines.enrichment.key_terms import enrich_key_terms

CURRENT_ENRICH_VERSION = 1
BATCH_SIZE = 50


def _postings_needing_enrichment() -> list[str]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select id from job_postings
            where status = 'open'
              and (enrich_version is null or enrich_version < %s)
            order by posted_date desc nulls last
            """,
            (CURRENT_ENRICH_VERSION,),
        )
        return [str(r[0]) for r in cur.fetchall()]


def _mark_enriched(job_posting_ids: list[str]) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update job_postings
               set enrich_version = %s, last_enriched_at = now()
             where id = any(%s::uuid[])
            """,
            (CURRENT_ENRICH_VERSION, job_posting_ids),
        )
        conn.commit()


def run() -> None:
    ids = _postings_needing_enrichment()
    print(f"[enrichment] {len(ids)} posting(s) need enrichment", flush=True)
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i : i + BATCH_SIZE]
        embed_postings(batch)
        enrich_key_terms(batch)
        _mark_enriched(batch)
        print(f"[enrichment] {min(i + BATCH_SIZE, len(ids))}/{len(ids)} done", flush=True)
    print("[enrichment] finished", flush=True)


if __name__ == "__main__":
    run()
