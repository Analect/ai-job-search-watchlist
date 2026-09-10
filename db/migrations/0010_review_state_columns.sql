-- 017-enhanced-job-search: independent per-posting review-state signals
-- and the applications lifecycle table (data-model.md).

-- 1. New columns on job_postings
alter table job_postings
  add column if not exists reviewed boolean not null default false,
  add column if not exists flagged  boolean not null default false,
  add column if not exists promoted boolean not null default false,
  add column if not exists thumbs   text check (thumbs is null or thumbs in ('up', 'down')),
  add column if not exists comment  text;

-- 2. One-time backfill: fold legacy event-derived states into the new columns.
--    Every posting whose latest job_events row is 'flagged_for_advancement'
--    becomes flagged=true + reviewed=true.
--    Every posting with any other terminal event (incl. 'dismissed') becomes
--    reviewed=true only.  Postings with no events at all stay at the defaults.
with latest_event as (
  select distinct on (job_posting_id) job_posting_id, event_type
  from job_events
  order by job_posting_id, created_at desc
)
update job_postings jp
set reviewed = true,
    flagged  = (le.event_type = 'flagged_for_advancement')
from latest_event le
where le.job_posting_id = jp.id;

-- 3. applications table — one row per promoted posting, tracks the
--    resume-drafting and submission lifecycle (research.md §10).
create table if not exists applications (
  id                      uuid        primary key default gen_random_uuid(),
  job_posting_id          uuid        not null unique references job_postings(id),
  status                  text        not null default 'promoted'
    check (status in ('promoted', 'drafting', 'submitted', 'withdrawn')),
  resume_draft_branch     text,
  resume_draft_mr_url     text,
  resume_draft_path       text,
  cover_letter_draft_path text,
  draft_generated_at      timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

create index if not exists applications_status_idx on applications (status);
