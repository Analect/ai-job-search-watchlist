-- Follow-up to 0007: dlt also refuses to INSERT/UPDATE a typed varchar
-- parameter directly into a real uuid column ("column is of type uuid but
-- expression is of type character varying") - not just the JOIN dlt-hub/dlt#3749
-- covers. So dlt is kept off employer_id entirely: pipelines only ever write
-- employer_id_key (text), and this trigger derives the real uuid FK from it
-- on every insert/update, before NOT NULL is checked.
create or replace function job_postings_set_employer_id() returns trigger as $$
begin
  new.employer_id := new.employer_id_key::uuid;
  return new;
end;
$$ language plpgsql;

create trigger job_postings_set_employer_id
  before insert or update on job_postings
  for each row execute function job_postings_set_employer_id();
