-- data-model.md: descriptions
create table descriptions (
  id                uuid primary key default gen_random_uuid(),
  job_posting_id    uuid not null references job_postings(id),
  locale            text not null default 'en',
  content           text not null,
  content_hash      text not null,
  created_at        timestamptz not null default now(),

  unique (job_posting_id, locale)
);
