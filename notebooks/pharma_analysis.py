import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # Pharmaceuticals & Biotech watchlist explorer

        Explores `jseek_companies` for the **Pharmaceuticals & Biotech** industry
        (jseek id=18), cross-references against the live `employers` watchlist,
        and provides an interactive add-to-watchlist flow.

        **Requires** `JOB_SEARCH_PG_DSN` in the environment — same DSN every
        pipeline uses (`pipelines/common/db.py`). Running locally needs the
        WireGuard route to Supabase or an SSH tunnel.

        Calls `add_to_watchlist()` directly — the same function
        `POST /watchlist/{slug}` calls — so no HTTP plumbing is needed and the
        write path is identical to the map UI.
        """
    )
    return (mo,)


@app.cell(hide_code=True)
def _():
    import pandas as pd

    from pipelines.common.db import get_connection
    from pipelines.common.watchlist import add_to_watchlist

    return add_to_watchlist, get_connection, pd


@app.cell(hide_code=True)
def _(mo):
    import os
    from pathlib import Path

    # Try a .env file in the project root (standard local-dev convention).
    _project_root = Path("/home/mccoole/dev/gitlab/analysis/tooling/ai-job-search-watchlist")
    _env_path = _project_root / ".env"
    _loaded_from_file = False
    if _env_path.exists():
        for _line in _env_path.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())
        _loaded_from_file = True

    dsn_input = mo.ui.text(
        value=os.environ.get("JOB_SEARCH_PG_DSN", ""),
        placeholder="postgres://user:pass@host:5432/job_search",
        label="JOB_SEARCH_PG_DSN",
        kind="password",
        full_width=True,
    )

    _already_set = bool(os.environ.get("JOB_SEARCH_PG_DSN"))
    _output = (
        mo.callout(
            mo.md(f"DSN loaded {'from `.env`' if _loaded_from_file else 'from environment'} — ready to connect."),
            kind="success",
        )
        if _already_set
        else mo.vstack([
            mo.callout(
                mo.md("`JOB_SEARCH_PG_DSN` not found. Paste the DSN below and press Enter (or Tab)."),
                kind="warn",
            ),
            dsn_input,
        ])
    )
    _output
    return dsn_input, os


@app.cell(hide_code=True)
def _(dsn_input, os):
    # Propagate DSN from the input widget into os.environ so get_connection() finds it.
    # This cell re-runs whenever dsn_input.value changes.
    if dsn_input.value:
        os.environ["JOB_SEARCH_PG_DSN"] = dsn_input.value
        dsn_ready = True
    else:
        dsn_ready = bool(os.environ.get("JOB_SEARCH_PG_DSN"))
    return (dsn_ready,)


@app.cell(hide_code=True)
def _(dsn_ready, get_connection, mo, pd):
    mo.stop(
        not dsn_ready,
        mo.callout(mo.md("Enter `JOB_SEARCH_PG_DSN` above to load data."), kind="warn"),
    )

    AUTOMATED_ATS_TYPES = frozenset({
        "workday", "greenhouse", "lever", "ashby",
        "workable", "pinpoint", "oracle_hcm", "eightfold",
    })

    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select
                    c.slug,
                    c.name,
                    c.website,
                    c.employee_count_range,
                    string_agg(b.monitor_type, ', ' order by b.monitor_type) as board_types
                from jseek_companies c
                join jseek_industries i on i.id = c.industry_id::integer
                left join jseek_boards b on b.company_slug = c.slug
                where i.name = 'Pharmaceuticals & Biotech'
                group by c.slug, c.name, c.website, c.employee_count_range
                order by c.name
                """
            )
            rows = cur.fetchall()

        pharma_df = pd.DataFrame(
            rows,
            columns=["slug", "name", "website", "employee_count_range", "board_types"],
        )
        pharma_df["has_automated_board"] = pharma_df["board_types"].apply(
            lambda v: bool(v and any(t.strip() in AUTOMATED_ATS_TYPES for t in v.split(",")))
        )
        pharma_df = pharma_df.sort_values(
            ["has_automated_board", "name"], ascending=[False, True]
        ).reset_index(drop=True)
        pharma_load_error = None
    except Exception as e:
        pharma_df = pd.DataFrame(
            columns=["slug", "name", "website", "employee_count_range", "board_types", "has_automated_board"]
        )
        pharma_load_error = e

    pharma_df
    return pharma_df, pharma_load_error


@app.cell(hide_code=True)
def _(dsn_ready, get_connection, mo, pd):
    mo.stop(
        not dsn_ready,
        mo.md(""),
    )

    _OUR_PIPELINES = frozenset({
        "workday", "greenhouse", "lever", "ashby",
        "workable", "pinpoint", "oracle_hcm", "eightfold",
    })

    try:
        with get_connection() as _c, _c.cursor() as _cur:
            _cur.execute(
                """
                select
                    coalesce(b.monitor_type, '(no board listed)') as ats_type,
                    count(distinct c.slug) as company_count
                from jseek_companies c
                join jseek_industries i on i.id = c.industry_id::integer
                left join jseek_boards b on b.company_slug = c.slug
                where i.name = 'Pharmaceuticals & Biotech'
                group by b.monitor_type
                order by company_count desc
                """
            )
            _ats_rows = _cur.fetchall()

        ats_df = pd.DataFrame(_ats_rows, columns=["ats_type", "company_count"])
        ats_df["pipeline_exists"] = ats_df["ats_type"].isin(_OUR_PIPELINES)
        ats_df["status"] = ats_df["pipeline_exists"].map({True: "✓ pipeline exists", False: "✗ not yet supported"})

        mo.vstack([
            mo.md("### ATS coverage across Pharma & Biotech companies"),
            mo.md(
                f"**{ats_df[ats_df['pipeline_exists']]['company_count'].sum()} of "
                f"{ats_df['company_count'].sum()} companies** use an ATS we already have a pipeline for."
            ),
            mo.ui.table(ats_df[["ats_type", "company_count", "status"]], selection=None),
        ])
    except Exception as _e:
        mo.callout(mo.md(f"**DB error:** {_e}"), kind="danger")
    return


@app.cell(hide_code=True)
def _(get_connection, pd, pharma_df):
    try:
        with get_connection() as conn2, conn2.cursor() as cur2:
            cur2.execute("select slug from employers where short_listed = true")
            watchlist_slugs = {row[0] for row in cur2.fetchall()}
        watchlist_error = None
    except Exception as e2:
        watchlist_slugs = set()
        watchlist_error = e2

    if not pharma_df.empty and "slug" in pharma_df.columns:
        pharma_with_status = pharma_df.copy()
        pharma_with_status["on_watchlist"] = pharma_with_status["slug"].isin(watchlist_slugs)
        total_pharma = len(pharma_with_status)
        watching_count = int(pharma_with_status["on_watchlist"].sum())
        available_count = total_pharma - watching_count
    else:
        pharma_with_status = pd.DataFrame(
            columns=["slug", "name", "website", "employee_count_range",
                     "board_types", "has_automated_board", "on_watchlist"]
        )
        total_pharma = watching_count = available_count = 0

    pharma_with_status
    return (
        available_count,
        pharma_with_status,
        total_pharma,
        watching_count,
        watchlist_error,
    )


@app.cell(hide_code=True)
def _(
    available_count,
    mo,
    pharma_load_error,
    pharma_with_status,
    total_pharma,
    watching_count,
    watchlist_error,
):
    if pharma_load_error is not None:
        _output = mo.callout(mo.md(f"**DB error loading jseek pharma companies:** {pharma_load_error}"), kind="danger")
    elif watchlist_error is not None:
        _output = mo.callout(mo.md(f"**DB error loading watchlist:** {watchlist_error}"), kind="danger")
    else:
        _already = pharma_with_status[pharma_with_status["on_watchlist"]].drop(columns=["on_watchlist"])
        _not_yet = pharma_with_status[~pharma_with_status["on_watchlist"]].drop(columns=["on_watchlist"])
        _output = mo.vstack([
            mo.hstack([
                mo.stat(value=str(total_pharma), label="In jseek (Pharma & Biotech)"),
                mo.stat(value=str(watching_count), label="Already watching"),
                mo.stat(value=str(available_count), label="Available to add"),
            ]),
            mo.ui.tabs({
                f"Already watching ({len(_already)})": mo.ui.table(_already, selection=None),
                f"Available to add ({len(_not_yet)})": mo.ui.table(_not_yet, selection=None),
            }),
        ])

    _output
    return


@app.cell(hide_code=True)
def _(mo, pd, pharma_with_status):
    not_yet_df = (
        pharma_with_status[~pharma_with_status["on_watchlist"]]
        .drop(columns=["on_watchlist"])
        .reset_index(drop=True)
        if not pharma_with_status.empty
        else pd.DataFrame(columns=["slug", "name", "website", "employee_count_range", "board_types", "has_automated_board"])
    )

    if not not_yet_df.empty:
        company_selector = mo.ui.table(not_yet_df, selection="multi")
        _display = mo.vstack([
            mo.md("### Select companies to add to watchlist"),
            company_selector,
        ])
    else:
        company_selector = mo.ui.table(
            pd.DataFrame(columns=["slug", "name"]), selection="multi"
        )
        _display = mo.callout(
            mo.md("All jseek Pharma & Biotech companies are already on your watchlist, or none were found."),
            kind="info",
        )

    _display
    return (company_selector,)


@app.cell(hide_code=True)
def _(mo):
    add_button = mo.ui.run_button(label="Add selected to watchlist")
    add_button
    return (add_button,)


@app.cell(hide_code=True)
def _(add_button, add_to_watchlist, company_selector, mo):
    mo.stop(not add_button.value, mo.md("*Select companies above, then click **Add selected to watchlist**.*"))

    selected_rows = company_selector.value
    if not selected_rows:
        mo.callout(mo.md("No companies selected — tick at least one row in the table above."), kind="warn")
    else:
        added = []
        not_found = []
        for row in selected_rows:
            slug = row["slug"]
            result = add_to_watchlist(slug)
            if result is None:
                not_found.append(slug)
            else:
                added.append(row["name"])

        parts = []
        if added:
            parts.append(mo.callout(
                mo.md(f"**Added to watchlist ({len(added)}):** " + ", ".join(added)),
                kind="success",
            ))
        if not_found:
            parts.append(mo.callout(
                mo.md(f"**Not found in jseek ({len(not_found)}):** " + ", ".join(not_found)),
                kind="warn",
            ))
        mo.vstack(parts)
    return


@app.cell(hide_code=True)
def _(add_button, get_connection, mo, pd):
    mo.stop(not add_button.value)

    mo.md("### Current Pharma & Biotech watchlist")

    try:
        with get_connection() as conn3, conn3.cursor() as cur3:
            cur3.execute(
                """
                select slug, name, industry, ats_type, collection_supported
                  from employers
                 where short_listed = true
                   and industry ilike %(pat)s
                 order by name
                """,
                {"pat": "%pharma%"},
            )
            live_rows = cur3.fetchall()
        live_df = pd.DataFrame(
            live_rows,
            columns=["slug", "name", "industry", "ats_type", "collection_supported"],
        )
        if live_df.empty:
            mo.callout(mo.md("No Pharmaceuticals & Biotech companies on the watchlist yet."), kind="info")
        else:
            mo.ui.table(live_df, selection=None)
    except Exception as e3:
        mo.callout(mo.md(f"**DB error:** {e3}"), kind="danger")
    return


if __name__ == "__main__":
    app.run()
