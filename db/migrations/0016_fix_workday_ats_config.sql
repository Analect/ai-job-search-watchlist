-- 019-job-search-ux-fixes: T038 — correct ats_config for two employers whose
-- seeds captured an empty config, causing _target_location_ids() to return []
-- on every scrape run (T037 live debug-pod investigation confirmed root cause).
--
-- Bank of America: seed used the External_Career_Site board which has no
-- London/Dublin offices; the correct board is hosted under the GHR tenant
-- (bankofamerica.wd1.myworkdayjobs.com/wday/cxs/ghr/Lateral-EMEA/jobs).
-- Confirmed live: 5 target location IDs returned for London/Dublin.
--
-- Intel: seed used bankofamerica.wd1.myworkdayjobs.com/External_Career_Site
-- (wrong company slug); correct config is intel/External, but confirmed live
-- that this board serves Leixlip (not Dublin) and has no London office — so
-- consecutive_zero_postings will still increment. Recorded here so the config
-- at least points at the right board for future reference.
--
-- Idempotent: WHERE guards ensure re-runs are no-ops if config already updated.

DO $$
DECLARE
    bofA_rows  integer;
    intel_rows integer;
BEGIN
    UPDATE employers
    SET ats_config = '{"company":"ghr","wd_instance":"wd1","site":"Lateral-EMEA"}'::jsonb
    WHERE name = 'Bank of America'
      AND ats_type = 'workday'
      AND ats_config = '{}'::jsonb;
    GET DIAGNOSTICS bofA_rows = ROW_COUNT;

    UPDATE employers
    SET ats_config = '{"company":"intel","wd_instance":"wd1","site":"External"}'::jsonb
    WHERE name = 'Intel'
      AND ats_type = 'workday'
      AND ats_config = '{}'::jsonb;
    GET DIAGNOSTICS intel_rows = ROW_COUNT;

    RAISE NOTICE 'fix_workday_ats_config: Bank of America updated=%, Intel updated=%',
        bofA_rows, intel_rows;
END;
$$;
