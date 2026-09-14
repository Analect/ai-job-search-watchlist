"""018-job-search-ux-enrichment: automated dlt-based refresh of the four
jseek_* reference tables from the upstream jobseek repository's CSV exports.

Replaces the one-shot db/refresh_jseek_reference.py script that ran
manually on the Supabase VM. Deployed as a daily CronJob via the
jseek-refresh-pipeline OpenChoreo Component (openchoreo-flux-state).

Parsing: companies.csv's `extras` JSON column is expanded into
same_as (jsonb array of sameAs URLs) and wikidata_id (text) so
map_projection.py can serve them without a schema change at query time.
"""

import csv
import io
import json

import dlt
import requests

from pipelines.common.db import get_dlt_destination

_BASE_URL = (
    "https://raw.githubusercontent.com/colophon-group/jobseek"
    "/refs/heads/main/apps/crawler/data/"
)

_TIMEOUT = 30


def _fetch_csv(filename: str) -> list[dict]:
    resp = requests.get(_BASE_URL + filename, timeout=_TIMEOUT)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    return list(reader)


@dlt.resource(
    name="jseek_companies",
    primary_key="slug",
    write_disposition={"disposition": "merge", "strategy": "upsert"},
    columns={
        "industry_id": {"data_type": "text"},
        "same_as": {"data_type": "json"},
    },
)
def companies_resource():
    rows = _fetch_csv("companies.csv")
    print(f"[jseek] {len(rows)} companies fetched", flush=True)
    for row in rows:
        extras_raw = row.get("extras") or "{}"
        try:
            extras = json.loads(extras_raw)
        except (json.JSONDecodeError, TypeError):
            extras = {}

        same_as = extras.get("sameAs") or None
        wikidata_id = extras.get("wikidataId") or None
        logo_url = row.get("logo_url") or extras.get("logoUrl") or None
        icon_url = row.get("icon_url") or extras.get("iconUrl") or None

        yield {
            "slug": row["slug"],
            "name": row.get("name"),
            "website": row.get("website"),
            "industry_id": row.get("industry") or None,
            "employee_count_range": row.get("employee_count_range") or None,
            "same_as": same_as,
            "wikidata_id": wikidata_id,
            "logo_url": logo_url,
            "icon_url": icon_url,
        }


@dlt.resource(
    name="jseek_boards",
    primary_key=["company_slug", "board_slug"],
    write_disposition={"disposition": "merge", "strategy": "upsert"},
    columns={"monitor_config": {"data_type": "json"}},
)
def boards_resource():
    rows = _fetch_csv("boards.csv")
    print(f"[jseek] {len(rows)} boards fetched", flush=True)
    for row in rows:
        raw_config = row.get("monitor_config") or ""
        try:
            monitor_config = json.loads(raw_config) if raw_config.strip() else None
        except (json.JSONDecodeError, TypeError):
            monitor_config = None
        yield {
            "company_slug": row["company_slug"],
            "board_slug": row["board_slug"],
            "monitor_type": row.get("monitor_type"),
            "board_url": row.get("board_url"),
            "monitor_config": monitor_config,
        }


@dlt.resource(
    name="jseek_company_descriptions",
    primary_key=["company_slug", "locale"],
    write_disposition={"disposition": "merge", "strategy": "upsert"},
)
def descriptions_resource():
    # CSV is wide-format: slug, en, de, fr, it — one column per locale.
    # Only 'en' is consumed by map_projection.py; yield one row per company.
    rows = _fetch_csv("company_descriptions.csv")
    print(f"[jseek] {len(rows)} descriptions fetched", flush=True)
    for row in rows:
        slug = row.get("slug")
        description = row.get("en")
        if not slug or not description:
            continue
        yield {
            "company_slug": slug,
            "locale": "en",
            "description": description,
        }


def run() -> None:
    print("[jseek] pipeline starting", flush=True)
    pipeline = dlt.pipeline(
        pipeline_name="jseek-refresh",
        destination=get_dlt_destination(),
        dataset_name="public",
    )
    load_info = pipeline.run(
        [companies_resource(), boards_resource(), descriptions_resource()],
    )
    print("[jseek] pipeline finished", flush=True)
    print(load_info, flush=True)


if __name__ == "__main__":
    run()
