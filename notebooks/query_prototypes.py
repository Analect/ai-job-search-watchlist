import marimo

__generated_with = "0.23.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # Postings query prototype (T036)

        Validates the `GET /postings` filter shape
        (`job-search-api.contract.md`) against the real, live-collected
        `job_search` Postgres data — before it's coded as an endpoint
        (T037), per the user's preferred workflow (research.md §11).

        Uses `psycopg2` + `pandas` directly (both already project
        dependencies) rather than adding `duckdb` as a new dependency
        just for this prototype - a lightweight, ad hoc query tool
        doesn't need a DuckDB layer in front of Postgres the way the
        SWA project's data-mesh pipelines do.

        **Requires** `JOB_SEARCH_PG_DSN` in the environment (the same
        DSN every pipeline uses - `pipelines/common/db.py`). Running
        this locally needs the WireGuard route to Supabase or an SSH
        tunnel; running it in-cluster (e.g. via marimohub) has it for
        free through the `job-search-db-credentials` trait.
        """
    )
    return (mo,)


@app.cell
def _():
    import pandas as pd

    from pipelines.common.db import get_connection

    return get_connection, pd


@app.cell
def _(mo):
    location_filter = mo.ui.dropdown(
        options={"Any": None, "London": "london", "Dublin": "dublin", "Other": "other"},
        value="Any",
        label="Location",
    )
    status_filter = mo.ui.dropdown(
        options={"Any": None, "Open": "open", "Closed": "closed"},
        value="Any",
        label="Status",
    )
    review_state_filter = mo.ui.dropdown(
        options={
            "Any": None,
            "Unreviewed": "unreviewed",
            "Flagged for advancement": "flagged_for_advancement",
            "Dismissed": "dismissed",
        },
        value="Any",
        label="Review state",
    )
    query_text = mo.ui.text(label="Search (title/department)", placeholder="e.g. data engineer")
    limit = mo.ui.number(start=1, stop=500, value=50, label="Limit")
    offset = mo.ui.number(start=0, stop=100_000, value=0, label="Offset")

    mo.hstack([location_filter, status_filter, review_state_filter])
    return limit, location_filter, offset, query_text, review_state_filter, status_filter


@app.cell
def _(mo, query_text):
    mo.hstack([query_text])
    return


@app.cell
def _(
    get_connection,
    limit,
    location_filter,
    offset,
    pd,
    query_text,
    review_state_filter,
    status_filter,
):
    # Mirrors job-search-api.contract.md's GET /postings shape exactly:
    # review_state is derived per-posting from job_events' latest row
    # (data-model.md - "never a separately maintained column that can
    # drift"), never stored. `location` maps onto job_postings'
    # location_city, which is only ever set to a TARGET_CITIES value or
    # left null by the shared gazetteer/adapter pre-filters - "other"
    # means a real, non-null city that isn't a target city (a posting
    # from a worldwide-scope adapter like Greenhouse, not filtered to
    # London/Dublin at capture time).
    SQL = """
        with latest_event as (
            select distinct on (job_posting_id) job_posting_id, event_type
            from job_events
            order by job_posting_id, created_at desc
        )
        select
            jp.id,
            e.name as employer_name,
            jp.title,
            jp.location_city,
            jp.location_country,
            jp.posted_date,
            jp.status,
            coalesce(le.event_type, 'unreviewed') as review_state,
            jp.source_url
        from job_postings jp
        join employers e on e.id = jp.employer_id
        left join latest_event le on le.job_posting_id = jp.id
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
              %(review_state)s is null
              or coalesce(le.event_type, 'unreviewed') = %(review_state)s
          )
          and (
              %(query)s is null
              or jp.title ilike '%%' || %(query)s || '%%'
              or jp.department ilike '%%' || %(query)s || '%%'
          )
        order by jp.posted_date desc nulls last
        limit %(limit)s offset %(offset)s
    """
    params = {
        "location": location_filter.value,
        "status": status_filter.value,
        "review_state": review_state_filter.value,
        "query": query_text.value or None,
        "limit": int(limit.value),
        "offset": int(offset.value),
    }
    with get_connection() as conn:
        results = pd.read_sql(SQL, conn, params=params)

    COUNT_SQL = """
        with latest_event as (
            select distinct on (job_posting_id) job_posting_id, event_type
            from job_events
            order by job_posting_id, created_at desc
        )
        select count(*) as total
        from job_postings jp
        left join latest_event le on le.job_posting_id = jp.id
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
              %(review_state)s is null
              or coalesce(le.event_type, 'unreviewed') = %(review_state)s
          )
          and (
              %(query)s is null
              or jp.title ilike '%%' || %(query)s || '%%'
              or jp.department ilike '%%' || %(query)s || '%%'
          )
    """
    with get_connection() as conn2:
        total = pd.read_sql(COUNT_SQL, conn2, params=params)["total"].iloc[0]

    results, total
    return results, total


@app.cell
def _(mo, results, total):
    mo.vstack(
        [
            mo.md(f"**{total}** matching postings (showing {len(results)})"),
            mo.ui.table(results, page_size=25),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
