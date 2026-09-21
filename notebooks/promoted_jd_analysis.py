import marimo

__generated_with = "0.23.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # Promoted JD Analysis (018-drafting-quality-improvements Feature 1)

        Aggregates key terms, responsibilities, and requirements across all
        currently-promoted job postings.  Enrichment is pre-computed by the
        `promoted_enrichment` pipeline — no LLM calls here.

        **Output**: ranked frequency tables per category, plus a one-click
        export to `docs/specs/018-jd-analysis-output.md`.

        **Requires** `JOB_SEARCH_PG_DSN` **or** `PGHOST`/`PGDATABASE`/
        `PGUSER`/`PGPASSWORD` in the environment (automatic in marimohub
        sessions with the Supabase PostgreSQL integration configured).
        """
    )
    return (mo,)


@app.cell
def _():
    import collections
    import json
    from pathlib import Path

    import pandas as pd

    from pipelines.common.db import get_connection

    return Path, collections, get_connection, json, pd


@app.cell
def _(get_connection, pd):
    with get_connection() as _conn:
        rows = pd.read_sql(
            """
            select
                jp.id::text         as posting_id,
                jp.title,
                e.name              as employer,
                jp.key_terms,
                jp.enrichment
            from job_postings jp
            join employers e on e.id = jp.employer_id
            where jp.id in (
                select job_posting_id
                from applications
                where status not in ('withdrawn')
            )
              and jp.key_terms is not null
            order by jp.title
            """,
            _conn,
        )
    return (rows,)


@app.cell
def _(mo, rows):
    mo.md(f"**{len(rows)} promoted postings** with enrichment loaded.")


@app.cell
def _(collections, pd, rows):
    _counter = collections.Counter()
    for _terms in rows["key_terms"]:
        if _terms:
            for _t in _terms:
                _counter[_t.lower().strip()] += 1

    top_terms = pd.DataFrame(
        _counter.most_common(40),
        columns=["term", "count"],
    )
    top_terms["pct_of_roles"] = (top_terms["count"] / len(rows) * 100).round(0).astype(int)
    return (top_terms,)


@app.cell
def _(mo, top_terms):
    mo.md("## Key Terms — frequency across promoted postings")
    mo.ui.table(top_terms, selection=None)
    return ()


@app.cell
def _(collections, json, pd, rows):
    _resp = collections.Counter()
    _req = collections.Counter()

    for _, _row in rows.iterrows():
        _enr = _row["enrichment"]
        if isinstance(_enr, str):
            _enr = json.loads(_enr)
        if not _enr:
            continue
        for _r in _enr.get("responsibilities", []):
            _resp[_r.strip()] += 1
        for _r in _enr.get("requirements", []):
            _req[_r.strip()] += 1

    top_responsibilities = pd.DataFrame(
        _resp.most_common(30),
        columns=["responsibility", "count"],
    )
    top_requirements = pd.DataFrame(
        _req.most_common(30),
        columns=["requirement", "count"],
    )
    return top_requirements, top_responsibilities


@app.cell
def _(mo, top_responsibilities):
    mo.md("## Responsibilities — most commonly cited across roles")
    mo.ui.table(top_responsibilities, selection=None)
    return ()


@app.cell
def _(mo, top_requirements):
    mo.md("## Requirements — most commonly cited across roles")
    mo.ui.table(top_requirements, selection=None)
    return ()


@app.cell
def _(mo, rows):
    _display = rows[["title", "employer", "key_terms"]].copy()
    _display["key_terms"] = _display["key_terms"].apply(
        lambda t: ", ".join(t) if t else ""
    )
    mo.md(f"## Per-role breakdown ({len(rows)} postings)")
    mo.ui.table(_display, selection=None)
    return ()


@app.cell
def _(rows, top_requirements, top_responsibilities, top_terms):
    _n = len(rows)

    _lines = [
        "# Promoted JD Analysis — output",
        "",
        f"**{_n} promoted postings** analysed.  "
        "Generated from `notebooks/promoted_jd_analysis.py`.",
        "",
        "## Key Terms (ranked by frequency)",
        "",
        "| Term | Count | % of roles |",
        "|---|---|---|",
    ]
    for _, _r in top_terms.iterrows():
        _lines.append(f"| {_r['term']} | {_r['count']} | {_r['pct_of_roles']}% |")

    _lines += [
        "",
        "## Responsibilities (top 30)",
        "",
        "| Responsibility | Count |",
        "|---|---|",
    ]
    for _, _r in top_responsibilities.iterrows():
        _lines.append(f"| {_r['responsibility']} | {_r['count']} |")

    _lines += [
        "",
        "## Requirements (top 30)",
        "",
        "| Requirement | Count |",
        "|---|---|",
    ]
    for _, _r in top_requirements.iterrows():
        _lines.append(f"| {_r['requirement']} | {_r['count']} |")

    _lines += [
        "",
        "## Per-role key terms",
        "",
        "| Title | Employer | Key Terms |",
        "|---|---|---|",
    ]
    for _, _r in rows.iterrows():
        _terms = ", ".join(_r["key_terms"]) if _r["key_terms"] else "—"
        _lines.append(f"| {_r['title']} | {_r['employer']} | {_terms} |")

    analysis_md = "\n".join(_lines)
    return (analysis_md,)


@app.cell
def _(Path, analysis_md, mo):
    import os as _os

    _repo_root = Path(_os.environ.get("MARIMO_ROOT", Path(__file__).parent.parent))
    _out_path = _repo_root / "docs" / "specs" / "018-jd-analysis-output.md"

    export_btn = mo.ui.button(label=f"Export to {_out_path.relative_to(_repo_root)}")

    mo.vstack([
        mo.md("## Export"),
        export_btn,
    ])
    return (export_btn,)


@app.cell
def _(Path, analysis_md, export_btn, mo):
    import os as _os2

    if export_btn.value:
        _repo_root = Path(_os2.environ.get("MARIMO_ROOT", Path(__file__).parent.parent))
        _out = _repo_root / "docs" / "specs" / "018-jd-analysis-output.md"
        _out.parent.mkdir(parents=True, exist_ok=True)
        _out.write_text(analysis_md)
        mo.md(f"✓ Written to `{_out}`")


if __name__ == "__main__":
    app.run()
