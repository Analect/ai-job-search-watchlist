import marimo

__generated_with = "0.23.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # Similarity search (T065)

        Interactive UI over `pipelines/common/similarity.py`'s
        `find_similar` — the SAME implementation
        `GET /postings/{id}/similar` (`api/app.py`) and the MCP
        server's `find_similar` tool call, not a reimplementation. Use
        this to eyeball result quality directly against live data
        before trusting it from the API or the assistant.

        **Requires** `JOB_SEARCH_PG_DSN` in the environment — same
        convention as `query_prototypes.py`.
        """
    )
    return (mo,)


@app.cell
def _():
    import pandas as pd

    from pipelines.common.db import get_connection
    from pipelines.common.similarity import find_similar

    return find_similar, get_connection, pd


@app.cell
def _(get_connection, pd):
    with get_connection() as _conn, _conn.cursor() as _cur:
        _cur.execute(
            """
            select jp.id, e.name as employer, jp.title
              from job_postings jp
              join employers e on e.id = jp.employer_id
             where jp.status = 'open' and jp.embedding is not null
             order by e.name, jp.title
            """
        )
        _rows = _cur.fetchall()

    postings_df = pd.DataFrame(_rows, columns=["id", "employer", "title"])
    return (postings_df,)


@app.cell
def _(mo, postings_df):
    posting_picker = mo.ui.dropdown(
        options={f"{row.employer} — {row.title}": str(row.id) for row in postings_df.itertuples()},
        label="Posting (leave unset to use the most recently flagged-for-advancement posting, matching find_similar's no-argument behavior)",
    )
    limit = mo.ui.slider(start=1, stop=20, value=5, label="Results")
    mo.vstack([posting_picker, limit])
    return limit, posting_picker


@app.cell
def _(find_similar, limit, mo, pd, posting_picker):
    result = find_similar(job_posting_id=posting_picker.value, limit=limit.value)

    if "message" in result:
        mo.md(f"*{result['message']}*")
        results_df = None
    else:
        results_df = pd.DataFrame(result["results"])
        mo.md(f"**{len(results_df)}** result(s):")
    return result, results_df


@app.cell
def _(mo, results_df):
    results_df if results_df is not None else mo.md("")
    return


if __name__ == "__main__":
    app.run()
