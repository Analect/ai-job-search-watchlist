-- data-model.md: employers
create extension if not exists pgcrypto;

create table employers (
  id                    uuid primary key default gen_random_uuid(),
  slug                  text not null unique,
  name                  text not null,
  website               text,
  industry              text,
  employee_count_range  text,
  ats_type              text not null,
  ats_config            jsonb not null default '{}',
  short_listed          boolean not null default false,
  active                boolean not null default true,
  collection_supported  boolean not null default false,
  consecutive_failures  integer not null default 0,
  last_error            text,
  last_successful_run_at timestamptz,
  gone_at               timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index employers_short_listed_idx on employers (short_listed) where short_listed = true;
create index employers_ats_type_idx on employers (ats_type);
