-- research.md addendum (2026-09-05): live, refreshable reference tables for
-- jseek's own company/board/industry/description registry — NOT a frozen
-- snapshot. `employers` is populated FROM these by slug join; the discovery
-- map (GET /map/coordinates) computes its TF-IDF+UMAP projection from these
-- tables live, not from a static Parquet file. Refreshed periodically by
-- db/refresh_jseek_reference.py, fetching directly from jseek's own
-- upstream CSVs (companies.csv/boards.csv/industries.csv/
-- company_descriptions.csv) — this data (CC BY-NC 4.0, distinct from
-- jseek's MIT-licensed crawler code per research.md's licensing note) is
-- stored here for this project's own personal use, not redistributed.
--
-- employers.slug is NOT a hard foreign key to jseek_companies.slug: an
-- employer added via FR-010's "not yet actively collected" path, or a
-- future FR-002 manual-add not sourced from jseek's registry at all, is a
-- valid employers row with no corresponding jseek_companies entry. The
-- relationship is "employers.slug MAY equal a jseek_companies.slug",
-- convention not constraint.

create table jseek_industries (
  id            integer primary key,
  name          text not null,
  keywords      text
);

create table jseek_companies (
  slug                  text primary key,
  name                  text not null,
  website               text,
  industry_id           integer references jseek_industries(id),
  employee_count_range  text,
  founded_year          integer,
  refreshed_at          timestamptz not null default now()
);

create table jseek_boards (
  id                uuid primary key default gen_random_uuid(),
  company_slug      text not null references jseek_companies(slug),
  board_slug        text not null,
  board_url         text,
  monitor_type      text,          -- jseek's own ats_type taxonomy
  monitor_config    jsonb,         -- real per-board connection params (tenant/token/site)
  refreshed_at      timestamptz not null default now(),

  unique (company_slug, board_slug)
);

create table jseek_company_descriptions (
  company_slug      text not null references jseek_companies(slug),
  locale            text not null default 'en',
  description       text,
  refreshed_at      timestamptz not null default now(),

  primary key (company_slug, locale)
);

create index jseek_boards_company_idx on jseek_boards (company_slug);
create index jseek_boards_monitor_type_idx on jseek_boards (monitor_type);
