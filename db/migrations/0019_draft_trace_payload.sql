-- 019: persist the initial LLM draft-generation trace locally in the
-- applications table so View Trace works regardless of OpenSearch availability
-- and survives index recycling.
--
-- draft_trace stores: model, input_tokens, output_tokens, duration_ms,
-- prompt (full user message), raw_response (before compile-fix / clean-prose).
--
-- NOTE: applications is owned by postgres (created via Supabase SQL editor)
-- so this must be applied by the postgres superuser, not job_search_app.
-- Route: ssh -i ~/.ssh/hetzner-supabase_ed25519 root@116.203.188.89 \
--   "docker exec supabase-db psql -U postgres -d job_search -f /tmp/0019.sql"
alter table applications
  add column if not exists draft_trace jsonb;
