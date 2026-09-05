"""T013: seed `employers` from the user's 69-company shortlist, joined
against the live jseek_companies/jseek_boards reference tables
(db/refresh_jseek_reference.py must have been run at least once first).

Runs ON THE SUPABASE VM ITSELF (same reasoning as
refresh_jseek_reference.py — no pandas/psycopg2 there, and this laptop
has no direct DB route). Loads db/seed_data/shortlist.csv (69 company
names — the user's OWN curation, not a copy of jseek's dataset) into a
temp table via `docker cp` + `\\copy`, then joins by exact name against
jseek_companies to resolve the canonical slug (never a locally-invented
slugify() — confirmed live that a naive slug function mismatches
jseek's own slugs for ~10% of the shortlist, e.g. "hugging-face" vs
their "huggingface" — see docs/openchoreo/ai-job-search/implementation/
20260905-job-search-db-provisioning.md).

Where a company has multiple jseek_boards rows (e.g. Deutsche Bank has
two distinct Workday boards), picks ONE per company — the one whose
monitor_type is among the 8 confirmed-automated ATS types if any
qualify, else the first by board_slug — matching this project's own
employers-are-one-row-per-company granularity (FR-001). The dropped
second board is a documented simplification, not silently lost data:
it's still visible in jseek_boards for anyone who needs it later.

Usage (on the VM): python3 seed_employers.py
"""

import subprocess
from pathlib import Path

CONTAINER = "supabase-db"
DATABASE = "job_search"
SHORTLIST_CSV = Path(__file__).parent / "seed_data" / "shortlist.csv"

# The 8 ATS types with confirmed, live-tested direct-API coverage
# (20260904-shortlist-direct-api-coverage.md) — the only ones with a
# pipelines/adapters/<type>.py adapter in this repo.
AUTOMATED_ATS_TYPES = (
    "workday", "greenhouse", "lever", "ashby",
    "workable", "pinpoint", "oracle_hcm", "eightfold",
)

SEED_SQL = f"""
create temporary table _shortlist_names (company_name text);
\\copy _shortlist_names FROM '/tmp/shortlist.csv' WITH (FORMAT csv, HEADER true)

with automated (ats_type, rank) as (
  values {",".join(f"('{t}', {i})" for i, t in enumerate(AUTOMATED_ATS_TYPES))}
),
ranked_boards as (
  select
    b.company_slug,
    b.monitor_type,
    b.monitor_config,
    row_number() over (
      partition by b.company_slug
      order by coalesce(a.rank, 999), b.board_slug
    ) as rn
  from jseek_boards b
  left join automated a on a.ats_type = b.monitor_type
),
matched as (
  select
    c.slug,
    c.name,
    c.website,
    i.name as industry,
    c.employee_count_range,
    rb.monitor_type as ats_type,
    coalesce(rb.monitor_config, '{{}}'::jsonb) as ats_config
  from _shortlist_names s
  join jseek_companies c on c.name = s.company_name
  left join jseek_industries i on i.id = c.industry_id
  left join ranked_boards rb on rb.company_slug = c.slug and rb.rn = 1
)
insert into employers (slug, name, website, industry, employee_count_range,
                        ats_type, ats_config, short_listed, active, collection_supported)
select
  slug, name, website, industry, employee_count_range,
  coalesce(ats_type, 'other'),
  ats_config,
  true, true,
  coalesce(ats_type, '') in ({",".join(f"'{t}'" for t in AUTOMATED_ATS_TYPES)})
from matched
on conflict (slug) do nothing;
"""


def main() -> None:
    subprocess.run(
        ["docker", "cp", str(SHORTLIST_CSV), f"{CONTAINER}:/tmp/shortlist.csv"], check=True
    )
    sql_path = Path("/tmp/_seed_employers_generated.sql")
    sql_path.write_text(SEED_SQL)
    subprocess.run(["docker", "cp", str(sql_path), f"{CONTAINER}:/tmp/seed_employers.sql"], check=True)
    subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", DATABASE,
         "-v", "ON_ERROR_STOP=1", "-f", "/tmp/seed_employers.sql"],
        check=True,
    )
    subprocess.run(
        ["docker", "exec", CONTAINER, "rm", "-f", "/tmp/shortlist.csv", "/tmp/seed_employers.sql"],
        check=True,
    )
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", DATABASE, "-t", "-A", "-c",
         "select count(*), count(*) filter (where collection_supported) from employers;"],
        check=True, capture_output=True, text=True,
    )
    total, supported = result.stdout.strip().split("|")
    print(f"Seeded employers: {total} total, {supported} collection_supported=true")


if __name__ == "__main__":
    main()
