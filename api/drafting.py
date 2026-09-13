"""017-enhanced-job-search (T038): LLM-assisted resume/cover-letter drafting
via AWS Bedrock (Claude), writing output to a new branch in the external
`mccoole/resume` repo via the GitLab REST API and opening an MR.

Uses the GitLab REST API directly (requests, already a project dep) rather
than the `glab` CLI binary — avoids packaging glab into the job-search-api
image; plan.md's open question resolved.  Credential injected as
GITLAB_RESUME_REPO_TOKEN from ESO (Vault: secret/gitlab/resume-repo-mr-token,
T037).
"""

import json
import os
import re
from datetime import datetime, timezone
from uuid import UUID

import boto3
import requests

_GITLAB_API = "https://gitlab.analect.com/api/v4"
_RESUME_PROJECT = "mccoole%2Fresume"  # URL-encoded project path
_TYPST_TEMPLATES_PATH = "typst/templates"
_PROFILE_DOCS = [
    "system/why-what-how-system.md",
    "system/pillars-career-arc-system.md",
]

# Cross-region inference profile ID. Must be one of the profiles covered by
# the bedrock-agent-user BedrockInferenceProfiles IAM policy. Override at
# deploy time via the DRAFTING_MODEL_ID env var (OpenChoreo environmentConfigs
# or a ConfigMap env entry) to swap models without a code rebuild.
_DRAFTING_MODEL_ID = os.environ.get(
    "DRAFTING_MODEL_ID", "us.anthropic.claude-sonnet-4-6"
)

_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _bedrock_client


def _gitlab_headers() -> dict:
    token = os.environ["GITLAB_RESUME_REPO_TOKEN"]
    return {"PRIVATE-TOKEN": token, "Content-Type": "application/json"}


def _fetch_template(path: str) -> str:
    headers = _gitlab_headers()
    import urllib.parse

    encoded = urllib.parse.quote(path, safe="")
    resp = requests.get(
        f"{_GITLAB_API}/projects/{_RESUME_PROJECT}/repository/files/{encoded}/raw",
        headers=headers,
        params={"ref": "main"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.text


def _slugify(text: str) -> str:
    """Turn a job title into a short branch-name-safe slug."""
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:40]


def _fetch_profile_docs() -> list[tuple[str, str]]:
    """Fetch candidate profile documents from the resume repo.

    Returns a list of (path, content) tuples. On individual fetch failure,
    logs a warning and skips that document rather than aborting the draft.
    """
    results = []
    for path in _PROFILE_DOCS:
        try:
            content = _fetch_template(path)
            results.append((path, content))
        except Exception as exc:
            print(f"[drafting] warning: could not fetch profile doc {path!r}: {exc}", flush=True)
    return results


def _draft_with_llm(
    description: str,
    resume_tmpl: str,
    letter_tmpl: str,
    application_notes: str | None = None,
) -> tuple[str, str]:
    """Call Bedrock Claude to draft the resume and cover letter.

    The prompt is grounded in the candidate's real profile documents
    (fetched from mccoole/resume) rather than asking the LLM to fill a
    blank template — this is the root-cause fix for fabricated claims in
    prior drafts (research.md §6, spec.md US7).
    """
    profile_docs = _fetch_profile_docs()
    profile_section = "\n\n".join(
        f"## {path}\n{content}" for path, content in profile_docs
    )

    notes_section = ""
    if application_notes and application_notes.strip():
        notes_section = f"\n\n## Candidate guidance\n{application_notes.strip()}"

    prompt = f"""You are helping draft job-application materials for a specific candidate.

CRITICAL RULE: Every claim you make about the candidate — employers, dates, metrics, \
credentials, skills — MUST be traceable to the candidate profile documents below. \
Do NOT invent, infer, or embellish anything not explicitly stated there.

{profile_section}{notes_section}

## Job description
{description}

## Resume structural template (typst — format reference only, not fill-in-the-blank)
{resume_tmpl}

## Cover letter structural template (typst — format reference only)
{letter_tmpl}

Using ONLY the facts in the candidate profile above, write:
1. A tailored resume (typst format, matching the template structure) \
highlighting experience relevant to this job description.
2. A cover letter (typst format) that is compelling, concise, and grounded \
in real experience from the profile.

Respond with EXACTLY the following JSON structure (no markdown fences, no preamble):
{{
  "resume": "<complete typst resume>",
  "cover_letter": "<complete typst cover letter>"
}}"""

    client = _get_bedrock_client()
    response = client.invoke_model(
        modelId=_DRAFTING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8000,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )
    body = json.loads(response["body"].read())
    text = body["content"][0]["text"]
    parsed = json.loads(text)
    return parsed["resume"], parsed["cover_letter"]


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


def merge_draft(mr_url: str) -> dict:
    """Merge the draft MR. Raises DraftAlreadyMergedError if already merged/closed.
    Returns {"final_url": "..."} on success."""
    m = re.search(r"/merge_requests/(\d+)", mr_url)
    if not m:
        raise ValueError(f"cannot parse MR IID from URL: {mr_url!r}")
    mr_iid = m.group(1)

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


def generate_drafts(job_posting_id: UUID | str, detail: dict) -> dict:
    """Generate resume/cover-letter drafts for a posting and push to the
    resume repo as a reviewable MR.  Returns the draft metadata dict."""
    from pipelines.common.applications import get as _get_application

    posting = detail["posting"]
    description = detail["description"]  # caller already checked it's not None
    title = posting.get("title", "role")
    employer = posting.get("employer_name", "company")

    app_row = _get_application(job_posting_id)
    application_notes: str | None = app_row.get("application_notes") if app_row else None

    now = datetime.now(tz=timezone.utc)
    date_str = now.strftime("%Y%m%d")
    slug = _slugify(f"{employer}-{title}")
    branch_name = f"{date_str}-{slug}"
    folder = branch_name

    resume_tmpl = _fetch_template(f"{_TYPST_TEMPLATES_PATH}/resume-template.typ")
    letter_tmpl = _fetch_template(f"{_TYPST_TEMPLATES_PATH}/letter-template.typ")

    resume_content, letter_content = _draft_with_llm(
        description, resume_tmpl, letter_tmpl, application_notes=application_notes
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
        "draft_model_id": _DRAFTING_MODEL_ID,
    }
