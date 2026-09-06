-- data-model.md / research.md #3 originally specified vector(1536) for
-- Bedrock Titan v2 embeddings, but Titan v2 (amazon.titan-embed-text-v2:0)
-- only supports 256/512/1024 dimensions -- confirmed live against the
-- real Bedrock API (1536 is rejected with a ValidationException). No
-- embeddings have been populated yet (T040 not yet run), so this is a
-- plain column-type change, not a data migration.
drop index if exists job_postings_embedding_idx;
alter table job_postings alter column embedding type vector(1024);
create index job_postings_embedding_idx on job_postings
  using hnsw (embedding vector_cosine_ops);
