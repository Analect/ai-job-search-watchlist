"""job-search-api.contract.md GET /postings and GET /postings/{id}, and
mcp-server-tools.contract.md's search_jobs/get_job_detail: the SINGLE
read implementation, shared by api/app.py's routes and
mcp_server/server.py's tools — same convention as events.py/similarity.py.

017-enhanced-job-search (T006/T016): returns new review-state columns
(reviewed, flagged, promoted, thumbs, comment, location_unknown) and a
derived priority-ordered review_state label; filters on the boolean
columns directly instead of deriving state from job_events.
"""

from uuid import UUID

from pipelines.common.db import get_connection

# Derived review_state label — priority order: promoted > flagged >
# thumbs_up/thumbs_down > reviewed > unreviewed (research.md §1).
_REVIEW_STATE_CASE = """
    case
        when jp.promoted then 'promoted'
        when jp.flagged   then 'flagged'
        when jp.thumbs = 'up'   then 'thumbs_up'
        when jp.thumbs = 'down' then 'thumbs_down'
        when jp.reviewed  then 'reviewed'
        else 'unreviewed'
    end
"""

_FILTERS_SQL = """
    and (%(status)s is null or jp.status = %(status)s)
    and (
        %(location)s is null
        or (%(location)s = 'london' and jp.location_city = 'London')
        or (%(location)s = 'dublin' and jp.location_city = 'Dublin')
        or (
            %(location)s = 'other'
            and (
                jp.location_city is null
                or jp.location_city not in ('London', 'Dublin')
            )
        )
    )
    and (
        %(review_state)s is null
        or (%(review_state)s = 'unreviewed'  and jp.reviewed = false and jp.flagged = false and jp.promoted = false and jp.thumbs is null)
        or (%(review_state)s = 'reviewed'    and jp.reviewed = true)
        or (%(review_state)s = 'flagged'     and jp.flagged  = true)
        or (%(review_state)s = 'promoted'    and jp.promoted = true)
        or (%(review_state)s = 'thumbs_up'   and jp.thumbs = 'up')
        or (%(review_state)s = 'thumbs_down' and jp.thumbs = 'down')
    )
    and (
        %(query)s is null
        or jp.title ilike '%%' || %(query)s || '%%'
        or jp.department ilike '%%' || %(query)s || '%%'
        or exists (select 1 from unnest(jp.key_terms) t where t ilike '%%' || %(query)s || '%%')
        or exists (
            select 1 from descriptions d
             where d.job_posting_id = jp.id
               and d.locale = 'en'
               and d.content ilike '%%' || %(query)s || '%%'
        )
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
            f"""
            select
                jp.id, e.name, jp.title, jp.location_city, jp.location_country,
                jp.posted_date, jp.status,
                jp.reviewed, jp.flagged, jp.promoted, jp.thumbs,
                jp.location_city is null as location_unknown,
                {_REVIEW_STATE_CASE} as review_state,
                jp.source_url
            from job_postings jp
            join employers e on e.id = jp.employer_id
            where 1=1
            """
            + _FILTERS_SQL
            + """
            order by jp.posted_date desc nulls last, jp.id
            limit %(limit)s offset %(offset)s
            """,
            params,
        )
        rows = cur.fetchall()

        cur.execute(
            f"""
            select count(*)
            from job_postings jp
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
                "reviewed": r[7],
                "flagged": r[8],
                "promoted": r[9],
                "thumbs": r[10],
                "location_unknown": r[11],
                "review_state": r[12],
                "source_url": r[13],
            }
            for r in rows
        ],
        "total": total,
    }


def bulk_mark_reviewed(posting_ids: list[str]) -> int:
    """Set reviewed=true on every listed posting not already reviewed.
    Returns the count actually flipped (idempotent — no-op on already-
    reviewed or unknown IDs, per FR-009a).
    """
    if not posting_ids:
        return 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update job_postings
               set reviewed = true
             where id = any(%s::uuid[])
               and reviewed = false
            """,
            (posting_ids,),
        )
        count = cur.rowcount
        conn.commit()
    return count


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
                      and (
                          jp.location_city is null
                          or jp.location_city not in ('London', 'Dublin')
                      )
                  )
              )
              and (
                  %(query)s is null
                  or jp.title ilike '%%' || %(query)s || '%%'
                  or jp.department ilike '%%' || %(query)s || '%%'
                  or exists (
                      select 1 from unnest(jp.key_terms) t where t ilike '%%' || %(query)s || '%%'
                  )
                  or exists (
                      select 1 from descriptions d
                       where d.job_posting_id = jp.id
                         and d.locale = 'en'
                         and d.content ilike '%%' || %(query)s || '%%'
                  )
              )
              and (
                  %(company)s is null
                  or e.name ilike '%%' || %(company)s || '%%'
                  or e.slug ilike '%%' || %(company)s || '%%'
              )
            order by jp.posted_date desc nulls last, jp.id
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
            f"""
            select jp.id, jp.employer_id, e.name, jp.title, jp.source_url,
                   jp.location_raw, jp.location_city, jp.location_region,
                   jp.location_country, jp.is_remote, jp.employment_type,
                   jp.department, jp.posted_date, jp.status, jp.key_terms,
                   jp.first_seen_at, jp.last_seen_at,
                   jp.reviewed, jp.flagged, jp.promoted, jp.thumbs, jp.comment,
                   jp.location_city is null as location_unknown,
                   {_REVIEW_STATE_CASE} as review_state
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
            "reviewed": row[17],
            "flagged": row[18],
            "promoted": row[19],
            "thumbs": row[20],
            "comment": row[21],
            "location_unknown": row[22],
            "review_state": row[23],
        },
        "description": desc_row[0] if desc_row else None,
        "events": [
            {"event_type": e[0], "source": e[1], "note": e[2], "created_at": e[3]} for e in events
        ],
    }
