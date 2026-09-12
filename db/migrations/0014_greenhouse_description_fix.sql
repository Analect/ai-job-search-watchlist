-- 018-job-search-ux-enrichment: one-time idempotent correction of doubly-
-- encoded HTML content in descriptions rows for Greenhouse-sourced postings.
--
-- Root cause: Greenhouse's content=true API parameter returns HTML that is
-- itself entity-escaped for some boards (e.g. `<h1>` arrives as `&lt;h1&gt;`).
-- The adapter passed this through unchanged; this migration corrects existing
-- stored rows. New ingests are fixed at the adapter/clean_description() layer.
--
-- The correction is idempotent: regexp_replace only touches rows that still
-- contain doubly-encoded tag markers; a row with no remaining `&lt;...&gt;`
-- patterns is a no-op on re-run.
--
-- Scope: descriptions.content for job_postings whose employer's ats_type = 'greenhouse'.

DO $$
DECLARE
    affected integer;
BEGIN
    UPDATE descriptions d
    SET content = regexp_replace(
        regexp_replace(
            regexp_replace(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            regexp_replace(
                                regexp_replace(
                                    regexp_replace(d.content,
                                        '&amp;', E'\\&', 'g'),
                                    '&lt;', '<', 'g'),
                                '&gt;', '>', 'g'),
                            '&quot;', '"', 'g'),
                        '&#39;', '''', 'g'),
                    '&nbsp;', ' ', 'g'),
                '&apos;', '''', 'g'),
            '&amp;', '&', 'g'),
        '\r\n', E'\n', 'g')
    FROM job_postings jp
    JOIN employers e ON e.id = jp.employer_id
    WHERE d.job_posting_id = jp.id
      AND e.ats_type = 'greenhouse'
      AND d.content ~ '&lt;/?\w[^&]*&gt;';

    GET DIAGNOSTICS affected = ROW_COUNT;
    RAISE NOTICE 'greenhouse_description_fix: corrected % description row(s)', affected;
END;
$$;
