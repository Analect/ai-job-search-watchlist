-- data-model.md: scrape_runs — the FR-008 per-employer health source of truth
create table scrape_runs (
  id                uuid primary key default gen_random_uuid(),
  employer_id       uuid not null references employers(id),
  pipeline_run_id   text,
  started_at        timestamptz not null default now(),
  completed_at      timestamptz,
  status            text not null default 'running',
  postings_found    integer,
  postings_new      integer,
  error_message     text
);

create index scrape_runs_employer_idx on scrape_runs (employer_id, started_at desc);
