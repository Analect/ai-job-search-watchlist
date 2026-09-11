-- 017-enhanced-job-search: async generate-drafts support.
-- draft_error: populated on background task failure, reset on retry.
-- draft_model_id: which Bedrock inference profile produced this draft (018 §5.5).
ALTER TABLE applications ADD COLUMN IF NOT EXISTS draft_error   TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS draft_model_id TEXT;
