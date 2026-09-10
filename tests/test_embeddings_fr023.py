"""T043/FR-023: embed_postings() must never include employers.name in the
text it sends to Bedrock Titan.  Similarity searches must be employer-agnostic
so that posting embeddings reflect job content, not who posted the job.

This is a static-analysis test — it inspects the SQL string in
embed_postings() without hitting the database or calling Bedrock,
so it runs freely in any environment.
"""

import ast
import inspect

import pytest


def _get_embed_postings_source() -> str:
    from pipelines.enrichment import embeddings
    src = inspect.getsource(embeddings.embed_postings)
    return src


def test_embed_postings_sql_does_not_select_employer_name():
    """The SELECT inside embed_postings() must not join employers or select
    employers.name — FR-023 requires that embedding input is purely
    description text (+ title fallback), not employer identity."""
    source = _get_embed_postings_source()
    src_lower = source.lower()
    assert "employers" not in src_lower, (
        "embed_postings() SQL references 'employers' table — "
        "FR-023 forbids including employer names in embedding input"
    )
    assert "e.name" not in src_lower, (
        "embed_postings() SQL selects 'e.name' — "
        "FR-023 forbids including employer names in embedding input"
    )


def test_embed_postings_input_columns():
    """The SELECT inside embed_postings() should only use job_postings and
    descriptions — confirmed by checking that no JOIN on 'employers' exists."""
    source = _get_embed_postings_source()
    assert "join employers" not in source.lower(), (
        "embed_postings() joins the employers table — "
        "FR-023 requires employer-agnostic embeddings"
    )
