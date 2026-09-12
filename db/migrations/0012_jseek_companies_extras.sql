alter table jseek_companies
    add column if not exists same_as     jsonb,
    add column if not exists wikidata_id text,
    add column if not exists logo_url    text,
    add column if not exists icon_url    text;
