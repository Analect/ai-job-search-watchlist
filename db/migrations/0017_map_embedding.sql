-- Separate embedding column for the Job Watch Map UMAP projection.
-- Uses title + key_terms as input (role-focused, employer-agnostic) rather
-- than the full description, so cross-employer role clustering emerges.
-- The existing `embedding` column (full description) is preserved for
-- /postings/{id}/similar and any future semantic search.
alter table job_postings
  add column if not exists map_embedding vector(1024);
