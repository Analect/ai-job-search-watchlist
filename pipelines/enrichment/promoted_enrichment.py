"""LLM-based deep enrichment for promoted job postings.

Replaces TF-IDF key_terms with Bedrock-extracted domain-aware terms and
adds structured key_responsibilities and key_requirements — stored in the
enrichment jsonb column.  Runs as a background task when a posting is
promoted so the data is ready by the time the user triggers draft generation.

Writes:
  job_postings.key_terms         — overwritten with LLM-extracted terms
  job_postings.enrichment        — jsonb with responsibilities/requirements
  job_postings.enrich_version    — bumped to distinguish LLM vs TF-IDF passes
  job_postings.last_enriched_at  — updated
"""

import json
import os
from datetime import datetime, timezone
from uuid import UUID

import boto3

from pipelines.common.db import get_connection
from pipelines.common.text_clean import html_to_text

_MODEL_ID = os.environ.get("DRAFTING_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
_MAX_DESC_CHARS = 12_000

_client = None


def _bedrock_client():
    global _client
    if _client is None:
        from botocore.config import Config
        _client = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            config=Config(read_timeout=120, connect_timeout=10),
        )
    return _client


_EXTRACTION_SYSTEM = """You are a technical recruiter assistant. Given a job description,
extract structured information as JSON. Be specific and concrete — prefer exact
technology names, tool names, and domain terms over vague descriptors.
Return only valid JSON, no markdown fences, no explanation."""

_EXTRACTION_PROMPT = """\
Analyse this job description and return a JSON object with exactly these three keys:

"key_terms": an array of 6-10 strings — specific technologies, programming languages,
  frameworks, platforms, cloud services, and domain terms that distinguish this role.
  Examples: "Python", "Kubernetes", "AWS Bedrock", "FastAPI", "LangChain", "PostgreSQL",
  "financial services", "quantitative finance", "MLOps". Do NOT include generic words
  like "engineering", "experience", "software", "cloud", "data", "design", "skills".

"responsibilities": an array of 5-8 strings — the key things this person will actually
  do in the role. One short sentence each. Concrete, not generic.

"requirements": an array of 5-8 strings — the qualifications and experience genuinely
  required (not preferred). One short sentence each. Include specific experience levels,
  domain knowledge, and technical prerequisites where stated.

Job title: {title}

Job description:
{description}"""


def extract_job_intelligence(description_text: str, title: str) -> dict:
    """Call Bedrock Claude to extract key_terms, responsibilities, requirements.

    Returns a dict with those three keys on success.
    Raises on Bedrock or JSON parse failure.
    """
    prompt = _EXTRACTION_PROMPT.format(
        title=title,
        description=description_text[:_MAX_DESC_CHARS],
    )
    response = _bedrock_client().invoke_model(
        modelId=_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "system": _EXTRACTION_SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )
    body = json.loads(response["body"].read())
    blocks = body.get("content", [])
    text = next(
        (b.get("text") for b in blocks if b.get("type") == "text" and b.get("text")),
        None,
    )
    if not text:
        raise RuntimeError(
            f"bedrock returned no text (stop_reason={body.get('stop_reason')!r})"
        )
    # Strip any accidental markdown fences the model adds despite instructions
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    result = json.loads(text)
    return {
        "key_terms": [str(t) for t in result.get("key_terms", [])],
        "responsibilities": [str(r) for r in result.get("responsibilities", [])],
        "requirements": [str(r) for r in result.get("requirements", [])],
    }


def enrich_promoted(job_posting_id: UUID | str) -> None:
    """Run LLM enrichment for a single promoted posting.

    Fetches the description, calls Bedrock, writes key_terms + enrichment.
    Logs and returns without raising on any failure so a background task
    error never surfaces to the user.
    """
    pid = str(job_posting_id)
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select jp.title,
                       coalesce(nullif(d.content, ''), jp.title) as text,
                       jp.enrich_version
                from job_postings jp
                left join descriptions d
                    on d.job_posting_id = jp.id and d.locale = 'en'
                where jp.id = %s
                """,
                (pid,),
            )
            row = cur.fetchone()
        if row is None:
            print(f"[promoted_enrichment] {pid}: posting not found — skipping", flush=True)
            return

        title, raw_text, enrich_version = row
        plain = html_to_text(raw_text) or title
        if not plain:
            print(f"[promoted_enrichment] {pid}: empty description — skipping", flush=True)
            return

        intelligence = extract_job_intelligence(plain, title)

        enrichment_payload = json.dumps({
            "v": 1,
            "extracted_at": datetime.now(tz=timezone.utc).isoformat(),
            "responsibilities": intelligence["responsibilities"],
            "requirements": intelligence["requirements"],
        })

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update job_postings
                   set key_terms        = %s,
                       enrichment       = %s::jsonb,
                       enrich_version   = coalesce(enrich_version, 0) + 1,
                       last_enriched_at = now()
                 where id = %s
                """,
                (intelligence["key_terms"], enrichment_payload, pid),
            )
            conn.commit()

        print(
            f"[promoted_enrichment] {pid}: enriched — "
            f"{len(intelligence['key_terms'])} terms, "
            f"{len(intelligence['responsibilities'])} responsibilities, "
            f"{len(intelligence['requirements'])} requirements",
            flush=True,
        )

    except Exception as exc:
        print(f"[promoted_enrichment] {pid}: failed — {exc}", flush=True)


def backfill_promoted() -> None:
    """Run enrich_promoted for all currently promoted postings.

    Skips postings whose enrichment jsonb already has v=1 (already done).
    Safe to re-run; idempotent per posting.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select jp.id
            from job_postings jp
            join applications a on a.job_posting_id = jp.id
            where jp.promoted = true
              and (
                jp.enrichment is null
                or (jp.enrichment->>'v') is distinct from '1'
              )
            order by a.created_at
            """
        )
        rows = cur.fetchall()

    ids = [str(r[0]) for r in rows]
    print(f"[promoted_enrichment] backfill: {len(ids)} postings to enrich", flush=True)
    for pid in ids:
        enrich_promoted(pid)
