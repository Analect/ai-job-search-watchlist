"""T040: Bedrock Titan v2 embeddings for enrichment (research.md §3).

Direct boto3 bedrock-runtime calls, not routed through rag-server's
EmbeddingsFactory — this is a periodic batch job over open postings'
descriptions, not a request/response caller of rag-server (research.md
§3's own reasoning).

MODEL_DIMENSIONS must match job_postings.embedding's actual column
type. Titan v2 only supports 256/512/1024 — confirmed live against the
real Bedrock API (1536, this project's original schema value, is
rejected outright); see db/migrations/0009_embedding_dimension.sql.
"""

import json
import os

import boto3

from pipelines.common.db import get_connection
from pipelines.common.text_clean import html_to_text

MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024

# Titan v2's input limit is measured in tokens (~8192), not characters —
# this is a conservative characters-per-token-ish truncation, not an
# exact count; good enough to avoid a hard API rejection on the rare
# very-long description.
_MAX_INPUT_CHARS = 20_000

_client = None


def _bedrock_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=os.environ["AWS_REGION"])
    return _client


def embed_text(text: str) -> list[float]:
    resp = _bedrock_client().invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {"inputText": text[:_MAX_INPUT_CHARS], "dimensions": EMBEDDING_DIMENSIONS}
        ),
    )
    body = json.loads(resp["body"].read())
    return body["embedding"]


def embed_postings(job_posting_ids: list[str]) -> None:
    """Compute and write embeddings for the given posting ids, reading
    each posting's captured description text (falling back to title
    when no description was ever captured for that posting)."""
    if not job_posting_ids:
        return
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select jp.id, coalesce(d.content, jp.title)
            from job_postings jp
            left join descriptions d on d.job_posting_id = jp.id and d.locale = 'en'
            where jp.id = any(%s::uuid[])
            """,
            (job_posting_ids,),
        )
        rows = cur.fetchall()
        for posting_id, text in rows:
            embedding = embed_text(html_to_text(text))
            # psycopg2 has no native pgvector adapter — format explicitly
            # as vector's own text input syntax and cast, rather than
            # adding the `pgvector` package just for this one write.
            vector_literal = "[" + ",".join(repr(v) for v in embedding) + "]"
            cur.execute(
                "update job_postings set embedding = %s::vector where id = %s",
                (vector_literal, str(posting_id)),
            )
        conn.commit()
