"""job-search-api.contract.md GET /postings and GET /postings/{id}, and
mcp-server-tools.contract.md's search_jobs/get_job_detail: the SINGLE
read implementation, shared by api/app.py's routes and
mcp_server/server.py's tools (research.md §11) — same convention as
events.py/similarity.py.
"""

from uuid import UUID

from pipelines.common.db import get_connection

_FILTERS_SQL = """
    and (%(status)s is null or jp.status = %(status)s)
    and (
        %(location)s is null
        or (%(location)s = 'london' and jp.location_city = 'London')
        or (%(location)s = 'dublin' and jp.location_city = 'Dublin')
        or (
            %(location)s = 'other'
            and jp.location_city is not null
            and jp.location_city not in ('London', 'Dublin')
        )
    )
    and (
        %(review_state)s is null
        or coalesce(le.event_type, 'unreviewed') = %(review_state)s
    )
    and (
        %(query)s is null
        or jp.title ilike '%%' || %(query)s || '%%'
        or jp.department ilike '%%' || %(query)s || '%%'
        or exists (select 1 from unnest(jp.key_terms) t where t ilike '%%' || %(query)s || '%%')
    )
"""

_LATEST_EVENT_CTE = """
    with latest_event as (
        select distinct on (job_posting_id) job_posting_id, event_type
        from job_events
        order by job_posting_id, created_at desc
    )
"""


def list_postings(
    location: str | None = None,
    status: str | None = None,
    review_state: str | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    params = {
        "location": location,
        "status": status,
        "review_state": review_state,
        "query": query,
        "limit": limit,
        "offset": offset,
    }

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            _LATEST_EVENT_CTE
            + """
            select
                jp.id, e.name, jp.title, jp.location_city, jp.location_country,
                jp.posted_date, jp.status, coalesce(le.event_type, 'unreviewed'),
                jp.source_url
            from job_postings jp
            join employers e on e.id = jp.employer_id
            left join latest_event le on le.job_posting_id = jp.id
            where 1=1
            """
            + _FILTERS_SQL
            + """
            order by jp.posted_date desc nulls last
            limit %(limit)s offset %(offset)s
            """,
            params,
        )
        rows = cur.fetchall()

        cur.execute(
            _LATEST_EVENT_CTE
            + """
            select count(*)
            from job_postings jp
            left join latest_event le on le.job_posting_id = jp.id
            where 1=1
            """
            + _FILTERS_SQL,
            params,
        )
        total = cur.fetchone()[0]

    return {
        "results": [
            {
                "id": r[0],
                "employer_name": r[1],
                "title": r[2],
                "location_city": r[3],
                "location_country": r[4],
                "posted_date": r[5],
                "status": r[6],
                "review_state": r[7],
                "source_url": r[8],
            }
            for r in rows
        ],
        "total": total,
    }


def search_jobs(
    query: str | None = None,
    location: str | None = None,
    company: str | None = None,
    status: str | None = "open",
    limit: int = 20,
) -> dict:
    """mcp-server-tools.contract.md's search_jobs — a distinct shape
    from list_postings() (a `company` filter, `status` defaulting to
    'open' not any, no offset/review_state, and an explicit
    empty-result message) rather than the same function with different
    defaults, since the two contracts genuinely diverged."""
    limit = min(max(limit, 1), 100)
    params = {
        "query": query,
        "location": location,
        "company": company,
        "status": status,
        "limit": limit,
    }
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select
                jp.id, e.name, jp.title, jp.location_city, jp.location_country,
                jp.posted_date, jp.status, jp.source_url
            from job_postings jp
            join employers e on e.id = jp.employer_id
            where 1=1
              and (%(status)s is null or jp.status = %(status)s)
              and (
                  %(location)s is null
                  or (%(location)s = 'london' and jp.location_city = 'London')
                  or (%(location)s = 'dublin' and jp.location_city = 'Dublin')
                  or (
                      %(location)s = 'other'
                      and jp.location_city is not null
                      and jp.location_city not in ('London', 'Dublin')
                  )
              )
              and (
                  %(query)s is null
                  or jp.title ilike '%%' || %(query)s || '%%'
                  or jp.department ilike '%%' || %(query)s || '%%'
                  or exists (
                      select 1 from unnest(jp.key_terms) t where t ilike '%%' || %(query)s || '%%'
                  )
              )
              and (
                  %(company)s is null
                  or e.name ilike '%%' || %(company)s || '%%'
                  or e.slug ilike '%%' || %(company)s || '%%'
              )
            order by jp.posted_date desc nulls last, jp.first_seen_at desc
            limit %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()

    results = [
        {
            "id": r[0],
            "employer_name": r[1],
            "title": r[2],
            "location_city": r[3],
            "location_country": r[4],
            "posted_date": r[5],
            "status": r[6],
            "source_url": r[7],
        }
        for r in rows
    ]
    if not results:
        return {"results": [], "message": "no postings matched"}
    return {"results": results}


def get_job_detail(job_posting_id: UUID | str) -> dict | None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select jp.id, jp.employer_id, e.name, jp.title, jp.source_url,
                   jp.location_raw, jp.location_city, jp.location_region,
                   jp.location_country, jp.is_remote, jp.employment_type,
                   jp.department, jp.posted_date, jp.status, jp.key_terms,
                   jp.first_seen_at, jp.last_seen_at
            from job_postings jp
            join employers e on e.id = jp.employer_id
            where jp.id = %s
            """,
            (str(job_posting_id),),
        )
        row = cur.fetchone()
        if row is None:
            return None

        cur.execute(
            "select content from descriptions where job_posting_id = %s and locale = 'en'",
            (str(job_posting_id),),
        )
        desc_row = cur.fetchone()

        cur.execute(
            """
            select event_type, source, note, created_at
            from job_events
            where job_posting_id = %s
            order by created_at desc
            """,
            (str(job_posting_id),),
        )
        events = cur.fetchall()

    return {
        "posting": {
            "id": row[0],
            "employer_id": row[1],
            "employer_name": row[2],
            "title": row[3],
            "source_url": row[4],
            "location_raw": row[5],
            "location_city": row[6],
            "location_region": row[7],
            "location_country": row[8],
            "is_remote": row[9],
            "employment_type": row[10],
            "department": row[11],
            "posted_date": row[12],
            "status": row[13],
            "key_terms": row[14],
            "first_seen_at": row[15],
            "last_seen_at": row[16],
        },
        "description": desc_row[0] if desc_row else None,
        "events": [
            {"event_type": e[0], "source": e[1], "note": e[2], "created_at": e[3]} for e in events
        ],
    }
