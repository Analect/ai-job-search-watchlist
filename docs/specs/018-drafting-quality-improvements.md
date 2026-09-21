# 018 — Drafting Quality Improvements

**Date:** 2026-09-21  
**Author:** Colum McCoole  
**Status:** Draft

---

## Overview

Three improvements to the LLM drafting pipeline (`api/drafting.py`) to raise the quality
of generated resume and cover-letter output:

1. **Promoted JD analysis** — extract and summarise the most common responsibilities,
   requirements, and technology signals across the 23 promoted jobs, to guide profile
   enrichment and identify gaps.
2. **Independent Projects enrichment** — extend `candidate-profile.md` with additional
   projects and wire embedding-similarity selection into the draft prompt so the most
   relevant projects are foregrounded per job.
3. **AI-writing removal pass** — after LLM generation, apply a second Bedrock pass
   driven by the `avoid-ai-writing` skill to strip AI-isms from both documents before
   they are committed to the MR branch.

---

## Feature 1 — Promoted JD analysis

### Goal

Produce a structured summary of the 23 promoted jobs — common responsibilities,
required and preferred skills, frequently cited technologies — so we know what to
add to the candidate profile and which project descriptions to write.

### Implementation

**Task A — Marimo notebook**  
`notebooks/promoted_jd_analysis.py`

- Query: `SELECT jp.title, jp.employer_name, d.content FROM job_postings jp JOIN descriptions d ON d.job_posting_id = jp.id WHERE jp.id IN (SELECT job_posting_id FROM applications WHERE status = 'promoted')`.
  (The `employer_name` is a view/join — adapt to actual schema.)
- Strip HTML from `d.content` (use `html.parser` or `BeautifulSoup` — already a likely dep).
- For each description, call Bedrock Claude with a structured-extraction prompt that
  returns JSON: `{responsibilities: [...], required: [...], preferred: [...], tech: [...]}`.
- Aggregate across all 23 jobs: count-sort each list, deduplicate near-synonyms.
- Render a ranked table in Marimo: top-N by frequency, with job-title breakdown.
- Export as `docs/specs/018-jd-analysis-output.md` (one-time reference artefact for
  profile/project decisions — not runtime data).

**Task B — Interpretation pass**  
After the notebook run, manually review the output and decide:
- Which skills/responsibilities are currently under-represented in `candidate-profile.md`.
- Which new Independent Projects entries to write (see Feature 2).
- Which Technical Skills lines need updating.

### Dependencies

None beyond existing deps (`psycopg2`, `boto3`, `html.parser`). Runs locally against
the Supabase DSN via `JOB_SEARCH_PG_DSN`.

---

## Feature 2 — Independent Projects enrichment

### Goal

Give the LLM a richer set of projects to reference during drafting. Currently only
`synthetic-wealth-adviser` is listed. New entries should be short (5–8 lines) and
written in the same factual register as the existing entry.

### 2a — Separate project files

Create `projects/` in the `mccoole/resume` repo. One `.md` file per project, named
`<slug>.md`. Each file contains the full factual description of that project — richer
than what fits in `candidate-profile.md`. `candidate-profile.md` retains a one-line
stub per project under `## Independent Projects` so it stays a tight index; the full
content lives in the project file.

**Rationale:** keeping full project descriptions out of `candidate-profile.md` prevents
that file bloating to the point where the LLM loses the ability to give individual
sections appropriate weight. The drafting pipeline fetches and injects each project file
as a distinct, labelled block — giving the model cleaner signal on what each project is.

| File | Why include |
|---|---|
| `projects/synthetic-wealth-adviser.md` | Expand the existing stub into a full description |
| `projects/ai-job-search-watchlist.md` | Platform engineering, FastAPI, Supabase, K3s, OpenChoreo, MCP, agentic pipelines |
| `projects/analect-blog.md` | Technical writing on platform/MLOps/agentic — positions the blog as a credibility signal |
| *(others from Feature 1 Task B)* | Add as per gap analysis |

**Template for a project file:**
```markdown
# <Project Name>

**Period:** <year>–<year or present>
**Collaborators:** <name(s) or "solo">
**Links:** <repo / live URL if public>

## Summary
One-sentence positioning statement.

## What it does
Two to four sentences on the problem it solves and how.

## Technical detail
- Key technology / architectural choices (bullet list)
- Outcomes or scale indicators if factual (e.g. "six years of simulated history for 50 synthetic clients")

## Relevance signal
One sentence on which job contexts this project speaks to most directly.
```

### 2b — Pipeline changes to fetch project files

`api/drafting.py` currently fetches `_FACTUAL_DOCS = ["system/candidate-profile.md"]`.
Extend `generate_drafts()` to also list and fetch `projects/*.md` from the resume repo,
then inject them as a separate section in the `_draft_with_llm()` user message.

```python
_PROJECTS_PATH = "projects"

def _fetch_project_files() -> list[tuple[str, str]]:
    """List projects/*.md and return (slug, content) pairs."""
    paths = [p for p in _list_repo_tree(_PROJECTS_PATH) if p.endswith(".md")]
    return _fetch_docs(paths)
```

Inject into the user message in `_draft_with_llm()`, between the Candidate Profile
block and the Job Description block:

```
## Independent Projects (factual — reference only what is listed here; do not invent)

### synthetic-wealth-adviser
<content of projects/synthetic-wealth-adviser.md>

### ai-job-search-watchlist
<content of projects/ai-job-search-watchlist.md>

...
```

The anti-fabrication rule in the system prompt already covers this; add one line:
"Project descriptions in the user message are factual. Reference only those listed —
do not mention projects not present."

### 2c — Embedding-similarity selection (deferred)

Revisit if the project list grows beyond ~7 entries and context cost becomes measurable.
At that point, rank by cosine similarity against the posting embedding and pass only
the top-k. No implementation now.

**File changes:**
- `mccoole/resume` repo — new `projects/` directory with per-project `.md` files;
  update one-line stubs in `system/candidate-profile.md`
- `api/drafting.py` — `_fetch_project_files()`, updated `_draft_with_llm()` user message

---

## Feature 3 — AI-writing removal pass

### Goal

After the LLM generates the resume and cover letter typst content, run an additional
pass that detects and rewrites AI-isms, so the final committed document reads as
authentic human prose.

### Approach

A **second Bedrock Claude call** within `_draft_with_llm()` (after the initial
generation), driven by the `avoid-ai-writing` skill. This is preferred over a Node.js
subprocess because:
- The job-search-api container does not have Node.js installed.
- Adding Node.js as a container dependency for a post-process script is heavyweight.
- A Bedrock call is already the established pattern; it keeps the pipeline uniform.
- The SKILL.md + patterns reference can be read once and cached.

### Implementation

**Step 1 — Read the skill assets at startup**

```python
_AVOID_AI_SKILL_DIR = os.environ.get(
    "AVOID_AI_SKILL_DIR",
    "/home/mccoole/dev/github/conorbronsdon/avoid-ai-writing",
)

def _load_avoid_ai_skill() -> str:
    """Read SKILL.md and references/patterns.md once; return combined system prompt."""
    skill_md = Path(_AVOID_AI_SKILL_DIR) / "SKILL.md"
    patterns_md = Path(_AVOID_AI_SKILL_DIR) / "references" / "patterns.md"
    parts = []
    for p in (skill_md, patterns_md):
        if p.exists():
            parts.append(p.read_text())
    return "\n\n---\n\n".join(parts)
```

In production (Kubernetes), mount the skill directory as a ConfigMap or copy it into
the image at build time (see §Deployment below).

**Step 2 — Clean pass function**

```python
def _clean_ai_writing(content: str, kind: str, model_id: str) -> str:
    """Run avoid-ai-writing rewrite pass on typst content.

    Only prose sections (Brief, cover-letter paragraphs) are targetted.
    Typst function calls, imports, and directives are explicitly excluded
    from rewriting to avoid compiler breakage.
    """
    skill_prompt = _load_avoid_ai_skill()  # cached after first call
    client = _get_bedrock_client()
    clean_prompt = (
        f"The following is a typst {kind} document for a job application. "
        "Rewrite ONLY the prose passages (the 'Brief' section content, and the "
        "cover letter paragraph bodies). Do NOT alter any typst syntax, "
        "function calls (#import, #show, #exp, #link, #icon, #letterSignature), "
        "section headings (= ...), or template structure. "
        "Return the complete typst file with prose passages cleaned of AI-isms "
        "and sounding like a human professional wrote them. "
        "No preamble, no explanation — just the corrected typst.\n\n"
        f"---\n\n{content}"
    )
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8000,
            "system": skill_prompt,
            "messages": [{"role": "user", "content": clean_prompt}],
        }),
    )
    body = json.loads(response["body"].read())
    blocks = body.get("content", [])
    text = next((b.get("text") for b in blocks if b.get("type") == "text" and b.get("text")), None)
    if not text:
        print(f"[drafting] avoid-ai-writing pass returned no content for {kind} — keeping original", flush=True)
        return content
    return text.strip()
```

**Step 3 — Wire into `generate_drafts()`**

After the compile-and-fix loop, before `_commit_files()`:

```python
# AI-writing removal pass
resume_content = _clean_ai_writing(resume_content, "resume", effective_model_id)
letter_content = _clean_ai_writing(letter_content, "cover_letter", effective_model_id)
```

The clean pass runs **after** the typst compile-fix loop, so any structural integrity
repairs are preserved. If the clean pass introduces a new syntax error (unlikely but
possible), the existing compile-and-fix loop would need to be re-run; for now,
log a warning and proceed — the user can re-draft.

**Optional — detect-only trace attribute**

Log the avoid-ai-writing score from the detector (Node CLI, if available) as an
OTel span attribute for observability. Gate on `AVOID_AI_DETECT_SCORE=1` env var
to avoid requiring Node.js in production by default.

### Deployment

**Development:** set `AVOID_AI_SKILL_DIR` to the local checkout path. The skill files
are already present at `/home/mccoole/dev/github/conorbronsdon/avoid-ai-writing`.

**Production (OpenChoreo / Kubernetes):** two options:
- Option A (simpler): copy `SKILL.md` and `references/patterns.md` into the
  `job-search-api` container image at build time (Dockerfile `COPY` step). Pin to a
  specific tag/commit of the avoid-ai-writing repo. Set `AVOID_AI_SKILL_DIR` to the
  copied path.
- Option B: mount a ConfigMap containing both files; reference via env var. Easier to
  update without a rebuild.

Recommended: Option A for initial implementation (version pins are explicit in the
Dockerfile), Option B if the skill files need frequent updates.

---

## Task breakdown

### Feature 1

| ID | Task | File(s) |
|----|------|---------|
| T-018-01 | Write promoted JD analysis notebook | `notebooks/promoted_jd_analysis.py` |
| T-018-02 | Run notebook, export analysis output | `docs/specs/018-jd-analysis-output.md` |
| T-018-03 | Review output, decide profile gaps | — (manual) |

### Feature 2

| ID | Task | File(s) |
|----|------|---------|
| T-018-04 | Create `projects/` in `mccoole/resume`, write per-project `.md` files | `mccoole/resume: projects/*.md` |
| T-018-05 | Update one-line stubs in `system/candidate-profile.md` to match | `mccoole/resume: system/candidate-profile.md` |
| T-018-06 | Implement `_fetch_project_files()` and update `_draft_with_llm()` user message | `api/drafting.py` |
| T-018-07 | Test: regenerate a draft for one promoted job, confirm project files appear in prompt | — |

### Feature 3

| ID | Task | File(s) |
|----|------|---------|
| T-018-09 | Implement `_load_avoid_ai_skill()` with caching | `api/drafting.py` |
| T-018-10 | Implement `_clean_ai_writing()` | `api/drafting.py` |
| T-018-11 | Wire clean pass into `generate_drafts()` after compile-fix loop | `api/drafting.py` |
| T-018-12 | Add `AVOID_AI_SKILL_DIR` to Dockerfile / OpenChoreo config | `Dockerfile`, component config |
| T-018-13 | Test: compare draft before/after clean pass for AI-ism score | — |

---

## Open questions

1. **Avoid-AI skill version pinning:** the skill is at v3.35.0. Should be pinned in the
   Dockerfile or locked via a git submodule to avoid surprise behaviour changes.

2. **Clean pass for the full typst file vs. prose-only extraction:** extracting just the
   prose, cleaning it, and splicing it back avoids any risk of typst corruption.
   Alternatively, instruct the model precisely (as in the prompt above). Decision: start
   with the full-file approach with explicit typst-preservation instructions; if compile
   errors emerge, switch to extraction/splice.

3. **Feature 1 tooling:** the analysis notebook needs HTML stripping. Confirm whether
   `beautifulsoup4` is already in `pyproject.toml` or needs adding.
