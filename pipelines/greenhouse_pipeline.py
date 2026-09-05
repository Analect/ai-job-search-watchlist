"""T032: dlt-wrapped Greenhouse pipeline (ats-adapter.contract.md's
mandatory shape) — the first end-to-end validation of the dlt +
Postgres + scrape_runs + closure/location-normalization wiring, before
building out the remaining 8 adapters on top of an unvalidated
foundation.
"""

import os

import dlt

from pipelines.adapters.greenhouse import fetch_postings
from pipelines.common.closure import apply_closure
from pipelines.common.db import get_connection, get_dlt_destination
from pipelines.common.location_normalize import apply_location_normalization
from pipelines.common.scrape_runs import complete_scrape_run, start_scrape_run
from pipelines.common.types import Employer, parse_date


def _active_employers(ats_type: str) -> list[Employer]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, slug, name, ats_type, ats_config from employers "
            "where active and ats_type = %s",
            (ats_type,),
        )
        employers = [
            Employer(id=r[0], slug=r[1], name=r[2], ats_type=r[3], ats_config=r[4] or {})
            for r in cur.fetchall()
        ]
    # Fast-iteration escape hatch: restrict to one employer by slug, e.g. for
    # cluster test runs while debugging the load stage without waiting on all
    # employers' fetches every time. Unset in production (empty = all employers).
    test_slug = os.environ.get("GREENHOUSE_TEST_EMPLOYER")
    if test_slug:
        employers = [e for e in employers if e.slug == test_slug]
    return employers


def _upsert_description(job_posting_external_id: str, employer_id: str, content: str) -> None:
    import hashlib

    content_hash = hashlib.sha256(content.encode()).hexdigest()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into descriptions (job_posting_id, locale, content, content_hash)
            select id, 'en', %s, %s from job_postings
             where employer_id = %s and external_id = %s
            on conflict (job_posting_id, locale) do update
              set content = excluded.content, content_hash = excluded.content_hash
              where descriptions.content_hash != excluded.content_hash
            """,
            (content, content_hash, employer_id, job_posting_external_id),
        )
        conn.commit()


@dlt.resource(
    name="greenhouse_postings",
    # employer_id itself stays a real uuid FK (populated below, not part of
    # the merge key); dlt's postgres merge has no native uuid type (dlt-hub/dlt#3749)
    # — its generated staging table always types merge-key columns as varchar,
    # which fails to JOIN against a real uuid column. employer_id_key is a
    # plain text shadow of the same value used only as dlt's merge key.
    primary_key=["employer_id_key", "external_id"],
    # dlt 1.x API: merge_strategy is a key in the write_disposition dict,
    # not a separate kwarg (contra the research.md §9/ats-adapter.contract.md
    # sketch, written before this was verified against a real dlt install —
    # "upsert" itself is still never omitted, only the syntax changed).
    write_disposition={"disposition": "merge", "strategy": "upsert"},
    # Without this hint dlt flattens the raw_payload dict into individual
    # raw_payload__<field> columns (its default for nested objects) instead
    # of writing it into our single jsonb column.
    columns={"raw_payload": {"data_type": "json"}},
)
def postings_resource(completed: list[dict]):
    """`completed` collects per-employer results as a side effect during
    dlt's extract phase. Closure/location-normalization/description-capture
    all read job_postings, but dlt fully exhausts this generator (across
    every employer) *before* normalizing/loading anything into the
    destination - calling those here, inline, would run them against a
    table that doesn't yet have this run's rows (proven: only postings
    left over from an *earlier* run's commit ever got a description; every
    employer freshly loaded by the same run silently got skipped). They
    now run in `run()`, after `pipeline.run()` returns and the data is
    actually committed.
    """
    employers = _active_employers("greenhouse")
    print(f"[greenhouse] {len(employers)} active employer(s) to fetch", flush=True)
    for employer in employers:
        print(f"[greenhouse] fetching {employer.slug} ({employer.id})...", flush=True)
        run_id = start_scrape_run(employer.id)
        external_ids_seen: list[str] = []
        try:
            postings = list(fetch_postings(employer))
            print(f"[greenhouse] {employer.slug}: {len(postings)} posting(s) fetched", flush=True)
            for p in postings:
                external_ids_seen.append(p["external_id"])
                yield {
                    # employer_id (the real uuid FK) is deliberately not
                    # written here - dlt also refuses a direct varchar-typed
                    # INSERT/UPDATE into a uuid column, not just the merge
                    # JOIN. A trigger (0008 migration) derives it from
                    # employer_id_key on every insert/update instead.
                    "employer_id_key": employer.id,
                    "external_id": p["external_id"],
                    "title": p["title"],
                    "source_url": p["source_url"],
                    "location_raw": p.get("location_raw"),
                    "location_city": p.get("location_city"),
                    "location_region": p.get("location_region"),
                    "location_country": p.get("location_country"),
                    "is_remote": p.get("is_remote"),
                    "employment_type": p.get("employment_type"),
                    "department": p.get("department"),
                    "posted_date": parse_date(p.get("posted_date")),
                    "raw_payload": p,
                }
            complete_scrape_run(run_id, status="success", postings_found=len(postings))
            completed.append(
                {
                    "employer_id": employer.id,
                    "external_ids_seen": external_ids_seen,
                    "postings": postings,
                }
            )
        except Exception as exc:
            print(f"[greenhouse] {employer.slug}: FAILED - {exc}", flush=True)
            complete_scrape_run(run_id, status="failed", error_message=str(exc))
            continue  # FR-009: one employer's failure must not stop the rest


def run() -> None:
    print("[greenhouse] pipeline starting", flush=True)
    pipeline = dlt.pipeline(
        pipeline_name="greenhouse-postings",
        destination=get_dlt_destination(),
        dataset_name="public",
    )
    completed: list[dict] = []
    load_info = pipeline.run(postings_resource(completed), table_name="job_postings")
    print("[greenhouse] pipeline finished", flush=True)
    print(load_info, flush=True)

    for result in completed:
        employer_id = result["employer_id"]
        apply_closure(employer_id, result["external_ids_seen"], run_status="success")
        apply_location_normalization(employer_id)
        for p in result["postings"]:
            if p.get("description_text"):
                _upsert_description(p["external_id"], employer_id, p["description_text"])
    print(f"[greenhouse] post-processing complete for {len(completed)} employer(s)", flush=True)


if __name__ == "__main__":
    run()
