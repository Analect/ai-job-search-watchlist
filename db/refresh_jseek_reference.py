"""Refresh jseek_companies/jseek_boards/jseek_industries/jseek_company_descriptions
from jseek's own upstream CSVs (research.md addendum, 2026-09-05).

Runs ON THE SUPABASE VM ITSELF, not on a developer machine — this VM
has no WireGuard-external-peer route from a laptop, but its own
`docker exec supabase-db psql` access is the established, working
pattern (see docs/openchoreo/ai-job-search/implementation/
20260905-job-search-db-provisioning.md). No pandas/psycopg2 dependency
— the VM has neither installed; uses only `requests` (present) plus
stdlib csv/json, and shells out to `docker cp` + `psql \\copy`.

Usage (on the VM):
  python3 refresh_jseek_reference.py

This is a REFRESH, not an incremental sync: each run truncates and
reloads all four tables from jseek's current upstream CSVs. Safe to
re-run periodically (a future scheduled-pipeline Component, not yet
built) since `employers` and `job_postings` are separate tables,
unaffected by this refresh.
"""

import csv
import io
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

BASE_URL = "https://raw.githubusercontent.com/colophon-group/jobseek/main/apps/crawler/data"
CONTAINER = "supabase-db"
DATABASE = "job_search"


def fetch_csv(name: str) -> list[dict]:
    resp = requests.get(f"{BASE_URL}/{name}", timeout=30)
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def write_clean_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})


def build_descriptions_long(rows: list[dict]) -> list[dict]:
    long_rows = []
    for row in rows:
        slug = row["slug"]
        for locale in ("en", "de", "fr", "it"):
            desc = row.get(locale, "").strip()
            if desc:
                long_rows.append(
                    {"company_slug": slug, "locale": locale, "description": desc}
                )
    return long_rows


def psql_copy(container: str, database: str, table: str, columns: list[str], csv_path: Path) -> None:
    container_path = f"/tmp/{csv_path.name}"
    subprocess.run(["docker", "cp", str(csv_path), f"{container}:{container_path}"], check=True)
    col_list = ",".join(columns)
    subprocess.run(
        [
            "docker", "exec", container, "psql", "-U", "postgres", "-d", database,
            "-v", "ON_ERROR_STOP=1", "-c",
            f"\\copy {table}({col_list}) FROM '{container_path}' WITH (FORMAT csv, HEADER true)",
        ],
        check=True,
    )
    subprocess.run(["docker", "exec", container, "rm", "-f", container_path], check=True)


def main() -> None:
    print("Fetching jseek's upstream CSVs...")
    companies = fetch_csv("companies.csv")
    boards = fetch_csv("boards.csv")
    industries = fetch_csv("industries.csv")
    descriptions = fetch_csv("company_descriptions.csv")
    print(f"  companies={len(companies)} boards={len(boards)} "
          f"industries={len(industries)} descriptions={len(descriptions)}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        write_clean_csv(tmp / "industries.csv", industries, ["id", "name", "keywords"])
        write_clean_csv(
            tmp / "companies.csv", companies,
            ["slug", "name", "website", "industry", "employee_count_range", "founded_year"],
        )
        write_clean_csv(
            tmp / "boards.csv", boards,
            ["company_slug", "board_slug", "board_url", "monitor_type", "monitor_config"],
        )
        write_clean_csv(
            tmp / "descriptions.csv", build_descriptions_long(descriptions),
            ["company_slug", "locale", "description"],
        )

        print("Truncating existing reference tables (CASCADE, FK-dependent)...")
        subprocess.run(
            ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", DATABASE,
             "-v", "ON_ERROR_STOP=1", "-c",
             "TRUNCATE jseek_boards, jseek_company_descriptions, jseek_companies, "
             "jseek_industries CASCADE;"],
            check=True,
        )

        print("Loading industries...")
        psql_copy(CONTAINER, DATABASE, "jseek_industries", ["id", "name", "keywords"], tmp / "industries.csv")
        print("Loading companies...")
        psql_copy(
            CONTAINER, DATABASE, "jseek_companies",
            ["slug", "name", "website", "industry_id", "employee_count_range", "founded_year"],
            tmp / "companies.csv",
        )
        print("Loading boards...")
        psql_copy(
            CONTAINER, DATABASE, "jseek_boards",
            ["company_slug", "board_slug", "board_url", "monitor_type", "monitor_config"],
            tmp / "boards.csv",
        )
        print("Loading descriptions...")
        psql_copy(
            CONTAINER, DATABASE, "jseek_company_descriptions",
            ["company_slug", "locale", "description"],
            tmp / "descriptions.csv",
        )

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
