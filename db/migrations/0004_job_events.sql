-- data-model.md: job_events — append-only, no updated_at, never overwritten
create table job_events (
  id                uuid primary key default gen_random_uuid(),
  job_posting_id    uuid not null references job_postings(id),
  event_type        text not null,
  source            text not null default 'user',
  note              text,
  created_at        timestamptz not null default now()
);

create index job_events_posting_idx on job_events (job_posting_id, created_at desc);
