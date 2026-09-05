"""T032: dlt-wrapped Greenhouse pipeline (ats-adapter.contract.md's
mandatory shape) — the first end-to-end validation of the dlt +
Postgres + scrape_runs + closure/location-normalization wiring, before
building out the remaining 8 adapters on top of an unvalidated
foundation.
"""

import dlt

from pipelines.adapters.greenhouse import fetch_postings
from pipelines.common.closure import apply_closure
from pipelines.common.db import get_connection, get_dlt_destination
from pipelines.common.location_normalize import apply_location_normalization
from pipelines.common.scrape_runs import complete_scrape_run, start_scrape_run
from pipelines.common.types import Employer


def _active_employers(ats_type: str) -> list[Employer]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, slug, name, ats_type, ats_config from employers "
            "where active and ats_type = %s",
            (ats_type,),
        )
        return [
            Employer(id=r[0], slug=r[1], name=r[2], ats_type=r[3], ats_config=r[4] or {})
            for r in cur.fetchall()
        ]


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
    primary_key=["employer_id", "external_id"],
    # dlt 1.x API: merge_strategy is a key in the write_disposition dict,
    # not a separate kwarg (contra the research.md §9/ats-adapter.contract.md
    # sketch, written before this was verified against a real dlt install —
    # "upsert" itself is still never omitted, only the syntax changed).
    write_disposition={"disposition": "merge", "strategy": "upsert"},
)
def postings_resource():
    for employer in _active_employers("greenhouse"):
        run_id = start_scrape_run(employer.id)
        external_ids_seen: list[str] = []
        try:
            postings = list(fetch_postings(employer))
            for p in postings:
                external_ids_seen.append(p["external_id"])
                yield {
                    "employer_id": employer.id,
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
                    "posted_date": p.get("posted_date"),
                    "raw_payload": p,
                }
            complete_scrape_run(run_id, status="success", postings_found=len(postings))
            apply_closure(employer.id, external_ids_seen, run_status="success")
            apply_location_normalization(employer.id)
            for p in postings:
                if p.get("description_text"):
                    _upsert_description(p["external_id"], employer.id, p["description_text"])
        except Exception as exc:
            complete_scrape_run(run_id, status="failed", error_message=str(exc))
            continue  # FR-009: one employer's failure must not stop the rest


def run() -> None:
    pipeline = dlt.pipeline(
        pipeline_name="greenhouse-postings",
        destination=get_dlt_destination(),
        dataset_name="public",
    )
    load_info = pipeline.run(postings_resource(), table_name="job_postings")
    print(load_info)


if __name__ == "__main__":
    run()
