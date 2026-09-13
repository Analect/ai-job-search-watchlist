-- FR-016: track employers that consistently return zero postings on successful
-- scrape runs. Independent of consecutive_failures (a run can succeed technically
-- but yield zero postings, which needs separate visibility).
alter table employers
    add column if not exists consecutive_zero_postings integer not null default 0;
