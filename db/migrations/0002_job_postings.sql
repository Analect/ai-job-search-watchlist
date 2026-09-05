-- data-model.md: job_postings
create extension if not exists vector;

create table job_postings (
  id                    uuid primary key default gen_random_uuid(),
  employer_id           uuid not null references employers(id),
  external_id           text not null,
  title                 text not null,
  source_url            text not null,
  location_raw          text,
  location_city         text,
  location_region       text,
  location_country      text,
  is_remote             boolean,
  employment_type       text,
  department            text,
  posted_date           date,
  first_seen_at         timestamptz not null default now(),
  last_seen_at          timestamptz not null default now(),
  missing_count         integer not null default 0,
  status                text not null default 'open',
  embedding             vector(1536),
  key_terms             text[],
  enrichment            jsonb,
  enrich_version        integer,
  last_enriched_at      timestamptz,
  raw_payload           jsonb not null,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),

  unique (employer_id, external_id)
);

create index job_postings_embedding_idx on job_postings
  using hnsw (embedding vector_cosine_ops);
create index job_postings_employer_status_idx on job_postings (employer_id, status);
create index job_postings_status_idx on job_postings (status);
