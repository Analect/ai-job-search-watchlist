-- 019-job-search-ux-fixes: store the OTel trace ID from the Bedrock LLM
-- draft call so the UI can retrieve spans via GET /applications/{id}/trace.
-- NOTE: applications is owned by postgres (created via Supabase SQL editor)
-- so this must be applied by the postgres superuser, not job_search_app.
-- Route: ssh -i ~/.ssh/hetzner-supabase_ed25519 root@116.203.188.89 "docker exec supabase-db psql -U postgres -d job_search -f /tmp/0018.sql"
alter table applications
  add column if not exists draft_trace_id text;
