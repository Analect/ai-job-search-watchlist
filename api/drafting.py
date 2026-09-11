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


def _draft_with_llm(description: str, resume_tmpl: str, letter_tmpl: str) -> tuple[str, str]:
    """Call Bedrock Claude to fill in the resume and cover-letter templates."""
    prompt = f"""You are helping draft job-application materials.

## Job description
{description}

## Resume template (typst)
{resume_tmpl}

## Cover letter template (typst)
{letter_tmpl}

Fill in the resume template with relevant experience tailored to this job description.
Then fill in the cover letter template with a compelling, concise cover letter.

Respond with EXACTLY the following JSON structure (no markdown fences, no preamble):
{{
  "resume": "<complete filled typst resume>",
  "cover_letter": "<complete filled typst cover letter>"
}}"""

    client = _get_bedrock_client()
    response = client.invoke_model(
        modelId="anthropic.claude-sonnet-4-5",
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


def generate_drafts(job_posting_id: UUID | str, detail: dict) -> dict:
    """Generate resume/cover-letter drafts for a posting and push to the
    resume repo as a reviewable MR.  Returns the draft metadata dict."""
    posting = detail["posting"]
    description = detail["description"]  # caller already checked it's not None
    title = posting.get("title", "role")
    employer = posting.get("employer_name", "company")

    now = datetime.now(tz=timezone.utc)
    date_str = now.strftime("%Y%m%d")
    slug = _slugify(f"{employer}-{title}")
    branch_name = f"{date_str}-{slug}"
    folder = branch_name

    resume_tmpl = _fetch_template(f"{_TYPST_TEMPLATES_PATH}/resume-template.typ")
    letter_tmpl = _fetch_template(f"{_TYPST_TEMPLATES_PATH}/letter-template.typ")

    resume_content, letter_content = _draft_with_llm(description, resume_tmpl, letter_tmpl)

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
    }
