# /// script
# dependencies = [
#     "numpy",
#     "altair",
# ]
# ///
# numpy/altair aren't in pyproject.toml (the pipeline code has no need for
# them) — declared here via PEP 723 inline metadata instead, which
# marimohub's own dependency resolution honors on top of the synced
# workspace's pyproject.toml (docs/syncing.md #dependencies).

import marimo

__generated_with = "0.23.10"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # Embeddings explore (T065)

        Interactive companion to `pipelines/enrichment/embeddings.py`'s
        Titan v2 embeddings (1024-dim, `job_postings.embedding`
        pgvector column). Where `similarity_search.py` (this same
        folder) answers "what's similar to this one posting", this
        notebook is for eyeballing the embedding space itself — how
        many postings actually have an embedding yet, what a raw
        cosine-distance neighbourhood looks like before it's wrapped
        in `find_similar`'s API-facing shape, and a 2D PCA scatter to
        spot obvious clustering (or the lack of it) by employer.

        **Requires** `JOB_SEARCH_PG_DSN` in the environment — same
        convention as `query_prototypes.py`.
        """
    )
    return (mo,)


@app.cell
def _():
    import numpy as np
    import pandas as pd

    from pipelines.common.db import get_connection

    return get_connection, np, pd


@app.cell
def _(get_connection, mo):
    with get_connection() as _conn, _conn.cursor() as _cur:
        _cur.execute("select count(*) from job_postings where embedding is not null")
        embedded_count = _cur.fetchone()[0]
        _cur.execute("select count(*) from job_postings where status = 'open'")
        open_count = _cur.fetchone()[0]

    mo.md(
        f"""
        **{embedded_count}** of **{open_count}** open postings have an
        embedding ({100 * embedded_count / open_count:.0f}% coverage,
        if any are open at all).
        """
    )
    return


@app.cell
def _(get_connection, pd):
    with get_connection() as _conn, _conn.cursor() as _cur:
        _cur.execute(
            """
            select jp.id, e.name as employer, jp.title, jp.location
              from job_postings jp
              join employers e on e.id = jp.employer_id
             where jp.status = 'open' and jp.embedding is not null
             order by e.name, jp.title
            """
        )
        _rows = _cur.fetchall()

    postings_df = pd.DataFrame(_rows, columns=["id", "employer", "title", "location"])
    return (postings_df,)


@app.cell
def _(mo, postings_df):
    posting_picker = mo.ui.dropdown(
        options={f"{row.employer} — {row.title}": str(row.id) for row in postings_df.itertuples()},
        label="Posting to inspect",
    )
    neighbour_limit = mo.ui.slider(start=1, stop=20, value=5, label="Neighbours to show")
    mo.hstack([posting_picker, neighbour_limit])
    return neighbour_limit, posting_picker


@app.cell
def _(get_connection, mo, neighbour_limit, np, posting_picker):
    if posting_picker.value is None:
        mo.md("*Pick a posting above.*")
        neighbours_df = None
    else:
        with get_connection() as _conn, _conn.cursor() as _cur:
            _cur.execute(
                "select embedding from job_postings where id = %s", (posting_picker.value,)
            )
            target_embedding = _cur.fetchone()[0]

            _cur.execute(
                """
                select jp.id, e.name, jp.title, jp.embedding <=> %s as distance
                  from job_postings jp
                  join employers e on e.id = jp.employer_id
                 where jp.status = 'open'
                   and jp.embedding is not null
                   and jp.id != %s
                 order by jp.embedding <=> %s
                 limit %s
                """,
                (target_embedding, posting_picker.value, target_embedding, neighbour_limit.value),
            )
            _rows = _cur.fetchall()

        import pandas as pd

        neighbours_df = pd.DataFrame(_rows, columns=["id", "employer", "title", "cosine_distance"])
        neighbours_df["similarity"] = 1 - neighbours_df["cosine_distance"]

        vec = np.array(target_embedding)
        mo.md(
            f"Target embedding: {vec.shape[0]} dims, L2 norm {np.linalg.norm(vec):.3f} "
            "(Titan v2 embeddings are not unit-normalized by the API — this is expected, "
            "not a data-quality signal)."
        )
    return neighbours_df, pd


@app.cell
def _(mo, neighbours_df):
    neighbours_df if neighbours_df is not None else mo.md("")
    return


@app.cell
def _(mo):
    mo.md("""
    ## 2D projection (PCA)

    A quick sanity-check scatter, not a polished visualization —
    `map_projection.py` (`api/map_projection.py`) already does the
    rigorous TF-IDF+UMAP version for company *descriptions*; this
    cell answers a narrower question: does the *posting embedding*
    space show any obvious employer clustering on its own, using
    the cheapest possible projection (PCA, no extra dependency
    beyond what's already installed for `numpy`/`pandas`).
    """)
    return


@app.cell
def _(get_connection, mo, np, pd):
    with get_connection() as _conn, _conn.cursor() as _cur:
        _cur.execute(
            """
            select jp.id, e.name as employer, jp.embedding
              from job_postings jp
              join employers e on e.id = jp.employer_id
             where jp.status = 'open' and jp.embedding is not null
            """
        )
        _rows = _cur.fetchall()

    if len(_rows) < 3:
        mo.md("*Not enough embedded postings yet for a 2D projection (need at least 3).*")
        projection_df = None
    else:
        ids, employers, vectors = zip(*_rows)
        matrix = np.array(vectors)
        centered = matrix - matrix.mean(axis=0)
        # Plain PCA via SVD -- no sklearn dependency needed for a 2-component
        # projection, matching this notebook's own "cheapest possible" framing.
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        coords = centered @ vt[:2].T
        projection_df = pd.DataFrame(
            {"employer": employers, "x": coords[:, 0], "y": coords[:, 1]}
        )
    return (projection_df,)


@app.cell
def _(mo, projection_df):
    if projection_df is None:
        mo.md("")
    else:
        mo.ui.altair_chart(
            __import__("altair")
            .Chart(projection_df)
            .mark_circle(size=80)
            .encode(x="x", y="y", color="employer", tooltip=["employer"])
            .properties(width=600, height=400)
        )
    return


@app.cell(hide_code=True)
def _():
    import marimo as mo

    mo.md(
        "T065 live proof: this cell was added via marimo-pair against the "
        "marimohub-poweruser sandbox, not typed by a human in the browser editor."
    )
    return (mo,)


if __name__ == "__main__":
    app.run()
