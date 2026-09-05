-- dlt's postgres merge/upsert has no native "uuid" column type (dlt-hub/dlt#3749):
-- its generated staging table always types merge-key columns as varchar, so a
-- JOIN against a real uuid column fails with "operator does not exist: uuid =
-- character varying". employer_id stays uuid (real FK, indexing, app queries);
-- employer_id_key is a plain text shadow of the same value, used only as dlt's
-- merge-key column so its generated JOIN compares varchar-to-varchar.
alter table job_postings add column employer_id_key text not null;

create index job_postings_merge_key_idx on job_postings (employer_id_key, external_id);
