"""T051: POST /watchlist/{slug}'s write path (job-search-api.contract.md,
FR-016/FR-017) — the map's click-to-add action.

Reuses db/seed_employers.py's exact board-ranking logic (the 8
automated-ATS-type preference, campus/intern/graduate deprioritization,
and the greenhouse/ashby/workable token-from-url fallback), scoped to a
single company instead of the whole shortlist CSV — one company add
shouldn't duplicate or drift from the seeding logic's own rules for
picking which of a company's several jseek_boards rows to use.
"""

from pipelines.common.db import get_connection

# Same 8 ATS types as db/seed_employers.py's AUTOMATED_ATS_TYPES.
_AUTOMATED_ATS_TYPES = (
    "workday",
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "pinpoint",
    "oracle_hcm",
    "eightfold",
)

_AUTOMATED_VALUES = ",".join(f"('{t}', {i})" for i, t in enumerate(_AUTOMATED_ATS_TYPES))
_AUTOMATED_IN = ",".join(f"'{t}'" for t in _AUTOMATED_ATS_TYPES)

_ADD_TO_WATCHLIST_SQL = f"""
with automated (ats_type, rank) as (
    values {_AUTOMATED_VALUES}
),
ranked_boards as (
    select
        b.company_slug,
        b.monitor_type,
        b.monitor_config,
        b.board_url,
        row_number() over (
            partition by b.company_slug
            order by coalesce(a.rank, 999),
                     (b.board_slug ~* 'campus|intern|graduate')::int,
                     b.board_slug
        ) as rn
    from jseek_boards b
    left join automated a on a.ats_type = b.monitor_type
    where b.company_slug = %(slug)s
),
matched as (
    select
        c.slug,
        c.name,
        c.website,
        i.name as industry,
        c.employee_count_range,
        rb.monitor_type as ats_type,
        case
            when rb.monitor_config is not null and rb.monitor_config != '{{}}'::jsonb
                then rb.monitor_config
            when rb.monitor_type = 'greenhouse' then
                jsonb_build_object('token',
                    regexp_replace(rb.board_url, '.*greenhouse\\.io/([\\w-]+).*', '\\1'))
            when rb.monitor_type = 'ashby' then
                jsonb_build_object('token',
                    regexp_replace(rb.board_url, '.*ashbyhq\\.com/([\\w-]+).*', '\\1'))
            when rb.monitor_type = 'workable' then
                jsonb_build_object('token',
                    regexp_replace(rb.board_url, '.*workable\\.com/([\\w-]+).*', '\\1'))
            when rb.monitor_type = 'eightfold' then
                coalesce(rb.monitor_config, '{{}}'::jsonb)
                    || jsonb_build_object('host',
                        regexp_replace(rb.board_url, '^https?://([^/]+).*', '\\1'))
            else coalesce(rb.monitor_config, '{{}}'::jsonb)
        end as ats_config
    from jseek_companies c
    left join jseek_industries i on i.id = c.industry_id
    left join ranked_boards rb on rb.company_slug = c.slug and rb.rn = 1
    where c.slug = %(slug)s
)
insert into employers (slug, name, website, industry, employee_count_range,
                        ats_type, ats_config, short_listed, active, collection_supported)
select
    slug, name, website, industry, employee_count_range,
    coalesce(ats_type, 'other'),
    ats_config,
    true, true,
    coalesce(ats_type, '') in ({_AUTOMATED_IN})
from matched
on conflict (slug) do update set short_listed = true
returning collection_supported
"""


def remove_from_watchlist(slug: str) -> dict | None:
    """Set employers.short_listed = false for this slug.
    Returns None if the slug isn't in the employers table at all.
    Idempotent — removing an already-unwatched employer is a no-op beyond
    re-asserting short_listed=false, mirroring add_to_watchlist's convention.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "update employers set short_listed = false where slug = %s returning slug",
            (slug,),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None
        conn.commit()
    return {"slug": slug, "short_listed": False}


def add_to_watchlist(slug: str) -> dict | None:
    """Idempotent by construction (FR-017): a duplicate add is a no-op
    beyond re-asserting short_listed=true. Returns None if `slug` isn't
    in jseek_companies at all (the map's own universe is jseek_companies,
    so this should only happen for a stale/invalid slug)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(_ADD_TO_WATCHLIST_SQL, {"slug": slug})
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None
        conn.commit()
    return {"slug": slug, "short_listed": True, "collection_supported": row[0]}
