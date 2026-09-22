"""017-enhanced-job-search (T038): LLM-assisted resume/cover-letter drafting
via AWS Bedrock (Claude), writing output to a new branch in the external
`mccoole/resume` repo via the GitLab REST API and opening an MR.

Uses the GitLab REST API directly (requests, already a project dep) rather
than the `glab` CLI binary — avoids packaging glab into the job-search-api
image; plan.md's open question resolved.  Credential injected as
GITLAB_RESUME_REPO_TOKEN from ESO (Vault: secret/gitlab/resume-repo-mr-token,
T037).
"""

import hashlib
import json
import os
import re
import time
from math import sqrt
from pathlib import Path
from datetime import datetime, timezone
from uuid import UUID

import boto3
import requests

from pipelines.common.text_clean import html_to_text

_GITLAB_API = "https://gitlab.analect.com/api/v4"
_RESUME_PROJECT = "mccoole%2Fresume"  # URL-encoded project path
_TYPST_TEMPLATES_PATH = "typst/templates"

# Skeleton templates — exact typst call syntax with content placeholders.
# Hardcoded rather than fetched so (a) no example content bleeds into model
# output, (b) we fully control problematic patterns (email escaping, no #link
# in letter body). The \@ escape is required: bare @word in a typst content
# block is a citation reference.
_RESUME_SKELETON = r"""#import "../templates/resume-template.typ": *

#show: cv.with(
  author: "Colum McCoole",
  contacts: (
    [#icon("../logos/home.svg") #link("https://analect.com/posts/")[Blog]],
    [#icon("../logos/mail.svg") #link("mailto:colum.mccoole@analect.com")],
    [#icon("../logos/mobile.png") #link("+353864491990")],
    [#icon("../logos/github.svg") #link("https://github.com/Analect")[Analect]],
    [#icon("../logos/linkedin.svg") #link("https://www.linkedin.com/in/colum-mccoole-746b946a/")[colum-mccoole-746b946a]],
  )
)

= Brief
[2–3 sentence positioning statement tailored to this specific role and employer.
Focus on the most relevant experience thread from the candidate profile.]

= Experience
#exp(
  "Employer Name",
  "Job Title",
  "City, Country",
  "Year – Year",
  [
    - [Achievement or responsibility bullet point]
    - [Another bullet point]
  ]
)

= Education
#exp(
  "Institution Name",
  "Degree / Qualification",
  "City, Country",
  "Year",
  []
)

= Certifications
#exp(
  "Issuing body",
  [#link("https://credly.com/...")[Certification name]],
  "Expiry: Month Year",
  "Year",
  ""
)

= Technical Skills
- *Category*: item, item, item
"""

_LETTER_SKELETON = r"""#import "../templates/letter-template.typ": *

#show: letter.with(
  sender: [
    Colum McCoole \
    [City, Country — from candidate-profile.md contact location] \
    colum.mccoole\@analect.com \
    [phone]
  ],
  recipient: [
    [Hiring Manager Name or "The Hiring Team"] \
    [Employer Name] \
    [City, Country]
  ],
  date: [[Date — e.g. 15 September 2026]],
  subject: [Re: [Job Title] — [Employer Name]],
  name: [Colum McCoole],
)

[Opening paragraph: genuine interest in this specific role at this employer — specific enough that it could not have been written for a different role. 2–3 sentences maximum.]

[Body paragraph: direct line from most relevant experience to what this role needs.
Draw on specific employers, achievements, and dates from the candidate profile. 3–4 sentences maximum.
Plain prose only — no typst function calls, no #link(), no #exp().]

[Body paragraph: name and briefly describe one independent project from the project files that most directly evidences a technical capability this role requires. Explain why it is relevant to this specific role in one sentence. 2–3 sentences total. Plain prose only.]

[Closing paragraph: brief call to action. 1–2 sentences. Plain prose only.]

#letterSignature("../logos/mccoole_signature.png")
"""

# Docs sent as the Bedrock system prompt — written as LLM role instructions
# ("You are a career-positioning assistant…").  They govern voice, framing
# rules, pillar selection logic, and the Why/What/How structure.
_SYSTEM_DOCS = [
    "system/why-what-how-system.md",
    "system/pillars-career-arc-system.md",
]

# Factual ground-truth document — authoritative for all dates, employers,
# locations, email, credentials.  Sent in the user turn so the model treats
# it as concrete input data rather than standing instruction.
_FACTUAL_DOCS = [
    "system/candidate-profile.md",
]

# Directory in the resume repo containing per-project detail files.
# Each *.md file is fetched and injected as a separate block in the user
# message, keeping candidate-profile.md lean while giving the model full
# project context.
_PROJECTS_PATH = "projects"

# Static PDF appended to every cover letter — slide-deck cover page.
# Stored in the resume repo; updated by committing a new file to that path.
_SLIDE_DECK_PATH = "assets/slide-deck-cover.pdf"

# Fixed paragraph injected before #letterSignature in every cover letter.
# Injected programmatically so it is always verbatim, never LLM-rewritten.
_SLIDE_DECK_PARAGRAPH = (
    "I'm attaching the cover of a slide-deck I use to convey ideas around AI. "
    "Should any of the team want to review the full version, then please let me "
    "know and I can easily email it."
)

# In-memory embedding cache for project files: content_hash -> vector.
# Avoids re-calling Titan on every draft when project files haven't changed.
_project_embedding_cache: dict[str, list[float]] = {}

# Cached clean-prose system prompt, loaded once from the file alongside this module.
_CLEAN_PROSE_PROMPT_PATH = Path(__file__).parent / "clean_prose_prompt.md"
_clean_prose_prompt: str | None = None


def _get_clean_prose_prompt() -> str:
    global _clean_prose_prompt
    if _clean_prose_prompt is None:
        try:
            _clean_prose_prompt = _CLEAN_PROSE_PROMPT_PATH.read_text(encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(
                f"[drafting] could not load clean_prose_prompt.md: {exc}"
            ) from exc
    return _clean_prose_prompt

# Cross-region inference profile ID. Must be one of the profiles covered by
# the bedrock-agent-user BedrockInferenceProfiles IAM policy. Override at
# deploy time via the DRAFTING_MODEL_ID env var (OpenChoreo environmentConfigs
# or a ConfigMap env entry) to swap models without a code rebuild.
_DRAFTING_MODEL_ID = os.environ.get(
    "DRAFTING_MODEL_ID", "us.anthropic.claude-sonnet-4-6"
)

_bedrock_client = None

# Available models for the draft generation drop-down. The default is set by
# _DRAFTING_MODEL_ID; callers may pass any of these IDs to override per-request.
AVAILABLE_DRAFT_MODELS = [
    "us.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-sonnet-5",
]


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        from botocore.config import Config
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            config=Config(read_timeout=300, connect_timeout=10),
        )
    return _bedrock_client


def _gitlab_headers() -> dict:
    token = os.environ["GITLAB_RESUME_REPO_TOKEN"]
    return {"PRIVATE-TOKEN": token, "Content-Type": "application/json"}


def _fetch_repo_file(path: str, ref: str = "main") -> bytes:
    import urllib.parse
    encoded = urllib.parse.quote(path, safe="")
    resp = requests.get(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/repository/files/{encoded}/raw",
        headers=_gitlab_headers(),
        params={"ref": ref},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.content


def _list_repo_tree(path: str, ref: str = "main") -> list[str]:
    files: list[str] = []
    page = 1
    while True:
        resp = requests.get(
            f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/repository/tree",
            headers=_gitlab_headers(),
            params={"path": path, "ref": ref, "recursive": True, "per_page": 100, "page": page},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json()
        for item in items:
            if item["type"] == "blob":
                files.append(item["path"])
        if len(items) < 100:
            break
        page += 1
    return files


def _fetch_typst_assets(tmp: "Path") -> None:
    """Fetch typst/templates and typst/logos from main into tmp/, mirroring
    the repo path so ../templates/ imports resolve from any typst/{folder}/."""
    from pathlib import Path as _Path
    for asset_dir in ("typst/templates", "typst/logos"):
        try:
            asset_paths = _list_repo_tree(asset_dir)
        except Exception:
            asset_paths = []
        for asset_path in asset_paths:
            try:
                dest = tmp / asset_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(_fetch_repo_file(asset_path))
            except Exception:
                pass


def _fetch_template(path: str) -> str:
    return _fetch_repo_file(path).decode()



def _slugify(text: str) -> str:
    """Turn a job title into a short branch-name-safe slug."""
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:40]


def _fetch_posting_embedding(job_posting_id: UUID | str) -> list[float] | None:
    """Return the stored Titan embedding for a posting, or None if absent."""
    from pipelines.common.db import get_connection
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "select embedding::text from job_postings where id = %s",
            (str(job_posting_id),),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return [float(x) for x in row[0].strip("[]").split(",")]


def _embed_project(content: str) -> list[float]:
    """Embed project content via Titan v2, caching by content hash."""
    from pipelines.enrichment.embeddings import embed_text
    key = hashlib.md5(content.encode()).hexdigest()
    if key not in _project_embedding_cache:
        _project_embedding_cache[key] = embed_text(content)
    return _project_embedding_cache[key]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sqrt(sum(x * x for x in a))
    mag_b = sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _rank_projects(
    project_files: list[tuple[str, str]],
    posting_embedding: list[float] | None,
    top_k: int = 3,
) -> list[tuple[str, str]]:
    """Return the top_k most relevant projects ranked by cosine similarity.

    Falls back to returning all projects unchanged when the posting has no
    stored embedding or when the project count is already <= top_k.
    Projects that fail to embed are retained with score 0 so they are not
    silently dropped.
    """
    if posting_embedding is None or len(project_files) <= top_k:
        return project_files

    scored: list[tuple[float, str, str]] = []
    for path, content in project_files:
        try:
            score = _cosine_similarity(posting_embedding, _embed_project(content))
        except Exception as exc:
            print(f"[drafting] warning: could not embed project {path!r}: {exc}", flush=True)
            score = 0.0
        scored.append((score, path, content))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [(path, content) for _, path, content in scored[:top_k]]


def _build_intelligence_text(job_intelligence: dict, title: str = "") -> str:
    """Build a dense, boilerplate-free text from extracted job intelligence.

    Used to produce a focused embedding for project ranking — more accurate
    than embedding the full job description which contains salary copy,
    benefits boilerplate, and generic HR language.
    """
    parts = []
    if title:
        parts.append(title)
    if job_intelligence.get("key_terms"):
        parts.append("Technologies: " + ", ".join(job_intelligence["key_terms"]))
    if job_intelligence.get("responsibilities"):
        parts.append("Responsibilities: " + ". ".join(job_intelligence["responsibilities"]))
    if job_intelligence.get("requirements"):
        parts.append("Requirements: " + ". ".join(job_intelligence["requirements"]))
    return "\n".join(parts)


def _fetch_project_files() -> list[tuple[str, str]]:
    """Fetch all *.md files under projects/ in the resume repo.

    Returns (slug, content) pairs sorted by slug, skipping any file that fails
    to fetch with a warning.  An empty list is returned gracefully if the
    directory does not exist or is empty.
    """
    try:
        paths = [p for p in _list_repo_tree(_PROJECTS_PATH) if p.endswith(".md")]
    except Exception as exc:
        print(f"[drafting] warning: could not list {_PROJECTS_PATH!r}: {exc}", flush=True)
        return []
    paths.sort()
    return _fetch_docs(paths)


def _fetch_docs(paths: list[str]) -> list[tuple[str, str]]:
    """Fetch a list of documents from the resume repo.

    Returns (path, content) tuples; skips with a warning on fetch failure.
    """
    results = []
    for path in paths:
        try:
            content = _fetch_template(path)
            results.append((path, content))
        except Exception as exc:
            print(f"[drafting] warning: could not fetch {path!r}: {exc}", flush=True)
    return results


def _draft_with_llm(
    description: str,
    resume_tmpl: str,
    letter_tmpl: str,
    application_notes: str | None = None,
    model_id: str | None = None,
    project_files: list[tuple[str, str]] | None = None,
    job_intelligence: dict | None = None,
) -> tuple[str, str]:
    """Call Bedrock Claude to draft the resume and cover letter.

    System prompt: why-what-how + pillars framing docs (written as LLM role
    instructions — "You are a career-positioning assistant…").

    User message: factual candidate profile (authoritative for all dates,
    employers, locations, email) + job description + templates + notes.
    The anti-fabrication rule explicitly flags that the factual profile
    supersedes any incidental references in the framing docs.
    """
    system_docs = _fetch_docs(_SYSTEM_DOCS)
    factual_docs = _fetch_docs(_FACTUAL_DOCS)

    # System prompt = framing/voice instructions (already written as system prompts)
    system_prompt = "\n\n---\n\n".join(content for _, content in system_docs)
    # Append a hard override so the model defers to candidate-profile for facts
    system_prompt += """

---

## Hard factual override rule

The framing documents above (Why/What/How, Pillars/Acts) contain illustrative \
date ranges, location references, and achievement periods used as narrative anchors. \
These are NOT authoritative CV data. For every factual claim in the output — \
employer names, exact employment dates, location, email address, certifications \
with expiry dates, education — use ONLY what is stated in the Candidate Profile \
section of the user message. If the Candidate Profile and the framing documents \
conflict on a fact, the Candidate Profile always wins. Do NOT invent or infer any \
fact not present in the Candidate Profile."""

    notes_section = ""
    if application_notes and application_notes.strip():
        notes_section = f"\n\n## Candidate guidance (from application notes)\n{application_notes.strip()}"

    factual_section = "\n\n".join(
        f"## {path}\n{content}" for path, content in factual_docs
    )

    projects_section = ""
    if project_files:
        blocks = []
        for path, content in project_files:
            slug = path.split("/")[-1].replace(".md", "")
            # Drop the ## Relevance signal section — it's meta-guidance for ranking,
            # not substance the LLM needs when drafting.
            trimmed = re.split(r"\n## Relevance signal\b", content, maxsplit=1)[0].strip()
            blocks.append(f"### {slug}\n{trimmed}")
        projects_section = (
            "\n\n## Independent Projects — full detail\n"
            "(Factual. Reference only projects listed here — do not invent others.)\n\n"
            + "\n\n".join(blocks)
        )

    intelligence_section = ""
    if job_intelligence:
        parts = []
        if job_intelligence.get("key_terms"):
            parts.append("### Key technologies and domain terms\n" + ", ".join(job_intelligence["key_terms"]))
        if job_intelligence.get("responsibilities"):
            parts.append("### Key responsibilities\n" + "\n".join(f"- {r}" for r in job_intelligence["responsibilities"]))
        if job_intelligence.get("requirements"):
            parts.append("### Key requirements\n" + "\n".join(f"- {r}" for r in job_intelligence["requirements"]))
        if parts:
            intelligence_section = (
                "\n\n## Pre-extracted job intelligence "
                "(use these to guide tailoring — more reliable than parsing the raw description)\n\n"
                + "\n\n".join(parts)
            )

    prompt = f"""## Candidate Profile (factual ground truth — authoritative for all dates, \
employers, locations, email, credentials)

{factual_section}{projects_section}{notes_section}

## Job description
{description}{intelligence_section}

## Resume skeleton (typst — use this exact call syntax and structure; replace placeholders with real content)
{resume_tmpl}

## Cover letter skeleton (typst — use this exact call syntax and structure; replace placeholders with real content)
{letter_tmpl}

## Critical typst syntax rules — MUST follow exactly
- The resume MUST start with: `#import "../templates/resume-template.typ": *`
  then `#show: cv.with(` (note the colon after `show` and `.with(`).
  NEVER write `#show cv(` — that is invalid typst and will not compile.
- The cover letter MUST start with: `#import "../templates/letter-template.typ": *`
  then `#show: letter.with(` (note the colon after `show` and `.with(`).
  NEVER write `#show letter(` — that is invalid typst and will not compile.
- Use `#exp(place, title, location, time, details)` for all experience/education entries.
- Use `= Section Title` for section headings (single equals sign).
- In the cover letter body, write plain prose only — NO `#link(...)`, NO `#exp(...)`,
  NO inline typst function calls. Every `[` must have a matching `]`; every `(` a matching `)`.
- Cover letter paragraphs MUST be SHORT: 2–3 sentences for the opening and closing,
  3–4 sentences maximum for body paragraphs. Do NOT write long dense paragraphs.
- The cover letter skeleton ends with `#letterSignature("../logos/mccoole_signature.png")` —
  preserve this line exactly as written.
- Do NOT use any typst functions, imports, or constructs not shown in the examples above.

Using the framing rules in the system prompt and ONLY the facts in the Candidate \
Profile above, write:
1. A tailored resume (typst format, following the example structure and syntax exactly) \
highlighting experience relevant to this job description.
2. A cover letter (typst format) that is compelling, concise, and grounded \
in real experience from the profile.

Output the resume first, then exactly this delimiter on its own line:
===COVER_LETTER===
Then output the cover letter. No markdown fences, no preamble, no explanation — \
just the two typst files separated by that delimiter."""

    effective_model_id = model_id if model_id else _DRAFTING_MODEL_ID
    client = _get_bedrock_client()

    try:
        from opentelemetry import trace as _otel_trace
        _tracer = _otel_trace.get_tracer("job-search-api.drafting")
        _span_ctx = _tracer.start_as_current_span("bedrock.invoke_model")
    except Exception:
        _span_ctx = None

    import contextlib
    t0 = time.perf_counter()
    with (_span_ctx if _span_ctx is not None else contextlib.nullcontext()) as span:
        if span is not None:
            try:
                span.set_attribute("gen_ai.system", "aws_bedrock")
                span.set_attribute("gen_ai.request.model", effective_model_id)
            except Exception:
                pass

        response = client.invoke_model(
            modelId=effective_model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 16000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": prompt}],
            }),
        )
        body = json.loads(response["body"].read())
        duration_ms = int((time.perf_counter() - t0) * 1000)

        usage = body.get("usage", {})
        if span is not None:
            try:
                span.set_attribute("gen_ai.usage.input_tokens", usage.get("input_tokens", 0))
                span.set_attribute("gen_ai.usage.output_tokens", usage.get("output_tokens", 0))
            except Exception:
                pass

            try:
                span.add_event("gen_ai.user.message", {"content": prompt})
            except Exception:
                pass

            try:
                _blocks = body.get("content", [])
                completion_text = next(
                    (b.get("text", "") for b in _blocks if b.get("type") == "text"),
                    "",
                )
                if completion_text:
                    span.add_event("gen_ai.assistant.message", {"content": completion_text})
            except Exception:
                pass

        trace_id = None
        if span is not None:
            try:
                ctx = span.get_span_context()
                if ctx.is_valid:
                    trace_id = format(ctx.trace_id, "032x")
            except Exception:
                pass

        stop_reason = body.get("stop_reason", "")
        content_blocks = body.get("content", [])
        text_blocks = [b.get("text") for b in content_blocks if b.get("type") == "text" and b.get("text")]
        if not text_blocks:
            print(f"[drafting] unexpected bedrock response — stop_reason={stop_reason!r} content={content_blocks!r}", flush=True)
            raise RuntimeError(f"bedrock returned no text content (stop_reason={stop_reason!r})")
        text = text_blocks[0]
        _DELIM = "===COVER_LETTER==="
        if _DELIM not in text:
            print(f"[drafting] delimiter not found in response from {effective_model_id} — stop_reason={stop_reason!r}", flush=True)
            print(f"[drafting] raw response (first 500 chars): {text[:500]!r}", flush=True)
            raise RuntimeError(f"model response missing delimiter '{_DELIM}'")
        resume_content, cover_letter_content = text.split(_DELIM, 1)

        trace_payload = {
            "model": effective_model_id,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "duration_ms": duration_ms,
            "prompt": prompt,
            "raw_response": text,
        }
        return resume_content.strip(), cover_letter_content.strip(), trace_id, effective_model_id, trace_payload


def _delete_branch(branch_name: str) -> None:
    """Delete a branch from the resume repo; no-op if it doesn't exist."""
    import urllib.parse
    encoded = urllib.parse.quote(branch_name, safe="")
    resp = requests.delete(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/repository/branches/{encoded}",
        headers=_gitlab_headers(),
        timeout=10,
    )
    if resp.status_code not in (200, 204, 404):
        resp.raise_for_status()


def _create_branch(branch_name: str) -> None:
    resp = requests.post(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/repository/branches",
        headers=_gitlab_headers(),
        json={"branch": branch_name, "ref": "main"},
        timeout=10,
    )
    resp.raise_for_status()


def _commit_files(branch_name: str, folder: str, files: dict[str, str]) -> None:
    actions = [
        {
            "action": "create",
            "file_path": f"typst/{folder}/{name}",
            "content": content,
            "encoding": "text",
        }
        for name, content in files.items()
    ]
    resp = requests.post(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/repository/commits",
        headers=_gitlab_headers(),
        json={
            "branch": branch_name,
            "commit_message": f"Add {folder} application drafts",
            "actions": actions,
        },
        timeout=20,
    )
    resp.raise_for_status()


def _open_mr(branch_name: str, title: str) -> str:
    resp = requests.post(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/merge_requests",
        headers=_gitlab_headers(),
        json={
            "source_branch": branch_name,
            "target_branch": "main",
            "title": f"Draft: {title}",
            "description": "Auto-generated drafts — review and edit before merging.",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["web_url"]


class DraftAlreadyMergedError(Exception):
    pass


def get_draft_files(branch: str, resume_path: str, cover_letter_path: str) -> dict:
    """Fetch the current typst content of both draft files from the MR branch."""
    import urllib.parse

    headers = _gitlab_headers()

    def _fetch(path: str) -> str:
        encoded = urllib.parse.quote(path, safe="")
        resp = requests.get(
            f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/repository/files/{encoded}/raw",
            headers=headers,
            params={"ref": branch},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.text

    return {"resume": _fetch(resume_path), "cover_letter": _fetch(cover_letter_path)}


def update_draft_files(
    branch: str,
    resume_path: str,
    cover_letter_path: str,
    resume: str,
    cover_letter: str,
) -> dict:
    """Commit updated resume and cover letter back to the MR branch in one commit."""
    resp = requests.post(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/repository/commits",
        headers=_gitlab_headers(),
        json={
            "branch": branch,
            "commit_message": "Update application drafts",
            "actions": [
                {"action": "update", "file_path": resume_path, "content": resume, "encoding": "text"},
                {"action": "update", "file_path": cover_letter_path, "content": cover_letter, "encoding": "text"},
            ],
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    committed_at = data.get("committed_date") or data.get("created_at", "")
    return {"committed_at": committed_at}


def close_mr(mr_url: str) -> None:
    """Close (not merge) the draft MR. No-ops if already closed or merged."""
    m = re.search(r"/merge_requests/(\d+)", mr_url)
    if not m:
        return
    mr_iid = m.group(1)
    requests.put(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/merge_requests/{mr_iid}",
        headers=_gitlab_headers(),
        json={"state_event": "close"},
        timeout=20,
    ).raise_for_status()


def merge_draft(mr_url: str) -> dict:
    """Merge the draft MR. Raises DraftAlreadyMergedError if already merged/closed.
    Returns {"final_url": "..."} on success."""
    m = re.search(r"/merge_requests/(\d+)", mr_url)
    if not m:
        raise ValueError(f"cannot parse MR IID from URL: {mr_url!r}")
    mr_iid = m.group(1)

    # Remove Draft: prefix so GitLab allows the merge (draft MRs return 405).
    mr_resp = requests.get(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/merge_requests/{mr_iid}",
        headers=_gitlab_headers(),
        timeout=10,
    )
    mr_resp.raise_for_status()
    current_title = mr_resp.json().get("title", "")
    if current_title.startswith("Draft: "):
        requests.put(
            f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/merge_requests/{mr_iid}",
            headers=_gitlab_headers(),
            json={"title": current_title[len("Draft: "):]},
            timeout=10,
        ).raise_for_status()

    resp = requests.put(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/merge_requests/{mr_iid}/merge",
        headers=_gitlab_headers(),
        timeout=20,
    )
    if resp.status_code == 405:
        raise DraftAlreadyMergedError("MR branch is already merged or closed")
    resp.raise_for_status()

    branch = resp.json().get("source_branch", "")
    final_url = f"https://gitlab.analect.com/mccoole/resume/-/tree/main/typst/{branch}"
    return {"final_url": final_url}


def _compile_typst_content(content: str, kind: str) -> tuple[bool, str]:
    """Write typst content to a temp dir, fetch assets, run typst compile.

    Returns (success, stderr). On success stderr is empty; on failure it
    contains the compiler error text.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        typst_root = tmp / "typst"
        draft_file = typst_root / "validate" / f"{kind}.typ"
        draft_file.parent.mkdir(parents=True, exist_ok=True)
        draft_file.write_text(content, encoding="utf-8")

        _fetch_typst_assets(tmp)

        out_pdf = draft_file.with_suffix(".pdf")
        result = subprocess.run(
            ["typst", "compile", "--root", str(typst_root), str(draft_file), str(out_pdf)],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.decode(errors="replace")


def _fix_typst_compile_error(content: str, kind: str, error: str, model_id: str) -> str:
    """Send a targeted correction request to the model for a compile failure.

    Returns the corrected typst (best-effort — the caller should try to
    compile the result and handle a second failure gracefully).
    """
    print(f"[drafting] typst {kind} compile error — requesting correction from {model_id}", flush=True)
    client = _get_bedrock_client()
    fix_prompt = (
        f"The following typst {kind} failed to compile with this error:\n\n"
        f"{error}\n\n"
        f"Here is the full typst content that failed:\n\n"
        f"{content}\n\n"
        "Return ONLY the corrected typst. No JSON wrapper, no markdown fences, "
        "no explanation — just the corrected typst file content."
    )
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8000,
            "messages": [{"role": "user", "content": fix_prompt}],
        }),
    )
    body = json.loads(response["body"].read())
    content_blocks = body.get("content", [])
    text_blocks = [b.get("text") for b in content_blocks if b.get("type") == "text" and b.get("text")]
    if not text_blocks:
        print(f"[drafting] fix-compile: unexpected bedrock response — stop_reason={body.get('stop_reason')!r} content={content_blocks!r}", flush=True)
        return content  # return original unchanged if correction call fails
    return text_blocks[0].strip()


def _clean_ai_writing(content: str, kind: str, model_id: str) -> str:
    """Run the clean-prose pass on a typst document.

    Uses the distilled avoid-ai-writing rules in clean_prose_prompt.md as the
    system prompt.  Only prose passages are rewritten; all typst syntax and
    factual content are preserved per the prompt's instructions.

    Returns the original content unchanged on any failure so a clean-pass
    error never blocks the draft from being committed.
    """
    try:
        system_prompt = _get_clean_prose_prompt()
    except Exception as exc:
        print(f"[drafting] clean pass skipped — {exc}", flush=True)
        return content

    client = _get_bedrock_client()
    try:
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 8000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": content}],
            }),
        )
        body = json.loads(response["body"].read())
        blocks = body.get("content", [])
        text = next(
            (b.get("text") for b in blocks if b.get("type") == "text" and b.get("text")),
            None,
        )
        if not text:
            print(
                f"[drafting] clean pass ({kind}): no text in response — "
                f"stop_reason={body.get('stop_reason')!r}; keeping original",
                flush=True,
            )
            return content
        return text.strip()
    except Exception as exc:
        print(f"[drafting] clean pass ({kind}) failed: {exc}; keeping original", flush=True)
        return content


def _merge_pdfs(pdf_bytes_list: list[bytes]) -> bytes:
    """Merge a list of PDF byte strings into one using pypdf."""
    from pypdf import PdfWriter
    import io
    writer = PdfWriter()
    for pdf_bytes in pdf_bytes_list:
        writer.append(io.BytesIO(pdf_bytes))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def generate_pdf(branch: str, draft_path: str) -> bytes:
    """Compile a typst draft to PDF and return the raw bytes.

    Fetches the draft .typ file from the MR branch and all assets under
    typst/templates/ and typst/logos/ from main, mirrors the repo's typst/
    subtree in a temp directory so relative imports resolve correctly, then
    runs `typst compile`.

    For cover letter drafts (path ends with _letter.typ), appends the
    slide-deck cover PDF from assets/slide-deck-cover.pdf in the resume repo.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        typst_root = tmp / "typst"

        draft_file = tmp / draft_path
        draft_file.parent.mkdir(parents=True, exist_ok=True)
        draft_file.write_bytes(_fetch_repo_file(draft_path, ref=branch))

        _fetch_typst_assets(tmp)

        out_pdf = draft_file.with_suffix(".pdf")
        result = subprocess.run(
            ["typst", "compile", "--root", str(typst_root), str(draft_file), str(out_pdf)],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            raise RuntimeError(f"typst compile failed: {stderr}")

        letter_pdf = out_pdf.read_bytes()

    # Append slide-deck cover for cover letter PDFs only.
    if draft_path.endswith("_letter.typ"):
        try:
            deck_pdf = _fetch_repo_file(_SLIDE_DECK_PATH)
            return _merge_pdfs([letter_pdf, deck_pdf])
        except Exception as exc:
            print(f"[drafting] warning: could not append slide deck PDF: {exc}", flush=True)

    return letter_pdf


def commit_draft_pdfs(branch: str, resume_path: str, cover_letter_path: str) -> None:
    """Compile both draft .typ files to PDF and commit them to the branch.

    Called just before merge so that the merged folder on main contains
    .pdf files alongside the .typ sources, matching the convention used by
    all other typst/ subfolders in mccoole/resume.

    Uses generate_pdf() for each file so the cover letter gets the
    slide-deck appendix automatically.
    """
    import base64

    actions = []
    for draft_path in (resume_path, cover_letter_path):
        try:
            pdf_bytes = generate_pdf(branch, draft_path)
        except Exception as exc:
            print(f"[drafting] warning: could not compile {draft_path} to PDF before merge: {exc}", flush=True)
            continue
        pdf_path = draft_path.replace(".typ", ".pdf")
        # Use "update" if the file already exists on the branch (e.g. retry),
        # otherwise "create".
        exists_resp = requests.head(
            f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/repository/files/{pdf_path.replace('/', '%2F')}",
            headers=_gitlab_headers(),
            params={"ref": branch},
            timeout=10,
        )
        action = "update" if exists_resp.status_code == 200 else "create"
        actions.append({
            "action": action,
            "file_path": pdf_path,
            "content": base64.b64encode(pdf_bytes).decode(),
            "encoding": "base64",
        })

    if not actions:
        return

    resp = requests.post(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/repository/commits",
        headers=_gitlab_headers(),
        json={
            "branch": branch,
            "commit_message": "Add compiled PDFs",
            "actions": actions,
        },
        timeout=60,
    )
    resp.raise_for_status()


def generate_drafts(job_posting_id: UUID | str, detail: dict, model_id: str | None = None) -> dict:
    """Generate resume/cover-letter drafts for a posting and push to the
    resume repo as a reviewable MR.  Returns the draft metadata dict."""
    from pipelines.common.applications import get as _get_application

    posting = detail["posting"]
    description = html_to_text(detail["description"])  # strip HTML tags/entities before passing to LLM
    title = posting.get("title", "role")
    employer = posting.get("employer_name", "company")

    app_row = _get_application(job_posting_id)
    application_notes: str | None = app_row.get("application_notes") if app_row else None

    now = datetime.now(tz=timezone.utc)
    date_str = now.strftime("%Y%m%d")
    # Include hour+minute so re-drafts on the same day get a unique branch name
    # and never collide with the branch being deleted in post_redraft.
    datetime_str = now.strftime("%Y%m%d-%H%M")
    slug = _slugify(f"{employer}-{title}")
    branch_name = f"{datetime_str}-{slug}"
    folder = branch_name

    project_files = _fetch_project_files()

    # Use pre-extracted job intelligence if available (written by enrich_promoted
    # when the posting was promoted). Falls back gracefully to None.
    raw_enrichment = posting.get("enrichment")
    job_intelligence: dict | None = None
    if isinstance(raw_enrichment, dict) and raw_enrichment.get("v") == 1:
        job_intelligence = raw_enrichment

    # For project ranking, prefer an embedding of the extracted intelligence
    # (dense, boilerplate-free) over the stored full-description embedding.
    # Falls back to the stored embedding when enrichment is not available.
    top_k = int(os.environ.get("DRAFT_TOP_K_PROJECTS", "3"))
    if job_intelligence:
        intel_text = _build_intelligence_text(job_intelligence, title=posting.get("title", ""))
        try:
            ranking_embedding = _embed_project(intel_text)
        except Exception as exc:
            print(f"[drafting] warning: could not embed intelligence text, falling back to posting embedding: {exc}", flush=True)
            ranking_embedding = _fetch_posting_embedding(job_posting_id)
    else:
        ranking_embedding = _fetch_posting_embedding(job_posting_id)
    ranked_projects = _rank_projects(project_files, ranking_embedding, top_k=top_k)

    date_human = now.strftime("%-d %B %Y")
    letter_tmpl_with_date = _LETTER_SKELETON.replace(
        "[Date — e.g. 15 September 2026]",
        date_human,
    )

    resume_content, letter_content, trace_id, effective_model_id, trace_payload = _draft_with_llm(
        description, _RESUME_SKELETON, letter_tmpl_with_date,
        application_notes=application_notes, model_id=model_id,
        project_files=ranked_projects or None,
        job_intelligence=job_intelligence,
    )

    # Compile-and-fix: attempt typst compile for each file; on error send a
    # targeted correction request to the model before committing.
    for kind, content_ref in [("resume", "resume_content"), ("cover_letter", "letter_content")]:
        content = resume_content if kind == "resume" else letter_content
        ok, error = _compile_typst_content(content, kind)
        if not ok:
            corrected = _fix_typst_compile_error(content, kind, error, effective_model_id)
            if kind == "resume":
                resume_content = corrected
            else:
                letter_content = corrected

    # Clean-prose pass: remove AI-isms from the generated prose.
    # Runs after compile-fix so any structural repairs are already in place.
    # Failures fall back to the pre-clean content — they never block the commit.
    resume_content = _clean_ai_writing(resume_content, "resume", effective_model_id)
    letter_content = _clean_ai_writing(letter_content, "cover_letter", effective_model_id)

    # Inject slide-deck paragraph before #letterSignature — always verbatim,
    # never subject to LLM rewriting or omission.
    sig_marker = '#letterSignature('
    if sig_marker in letter_content:
        letter_content = letter_content.replace(
            sig_marker,
            f"{_SLIDE_DECK_PARAGRAPH}\n\n{sig_marker}",
            1,
        )

    resume_filename = f"{date_str}_mccoole_resume.typ"
    letter_filename = f"{date_str}_mccoole_letter.typ"

    _create_branch(branch_name)
    _commit_files(branch_name, folder, {
        resume_filename: resume_content,
        letter_filename: letter_content,
    })
    mr_url = _open_mr(branch_name, f"{employer} — {title}")

    return {
        "status": "drafting",
        "resume_draft_branch": branch_name,
        "resume_draft_mr_url": mr_url,
        "resume_draft_path": f"typst/{folder}/{resume_filename}",
        "cover_letter_draft_path": f"typst/{folder}/{letter_filename}",
        "draft_generated_at": now.isoformat(),
        "draft_model_id": effective_model_id,
        "draft_trace_id": trace_id,
        "draft_trace": trace_payload,
    }
