"""
Batch re-draft a supplied list of job posting UUIDs.
Called by batch_redraft.sh; receives UUIDs as positional arguments.
Runs sequentially inside the pod — each draft call is synchronous.
"""
import sys, os
sys.path.insert(0, "/app")
os.chdir("/app")

from uuid import UUID

from api.app import _run_generate_drafts
from api.drafting import _delete_branch, close_mr
from pipelines.common import applications as apps_module
from pipelines.common.postings import get_job_detail

job_ids = sys.argv[1:]
if not job_ids:
    print("Usage: batch_redraft.py <uuid> [<uuid> ...]", flush=True)
    sys.exit(1)

print(f"Batch re-draft: {len(job_ids)} job(s)", flush=True)
print(flush=True)

for i, job_id in enumerate(job_ids, 1):
    app_row = apps_module.get(job_id)
    employer = app_row.get("employer_name", "?") if app_row else "?"
    print(f"[{i}/{len(job_ids)}] {employer} — {job_id}", flush=True)

    detail = get_job_detail(UUID(job_id))
    if detail is None or detail.get("description") is None:
        print(f"  SKIP — no job description captured", flush=True)
        print(flush=True)
        continue

    existing_mr_url = (app_row or {}).get("resume_draft_mr_url")
    if existing_mr_url:
        try:
            close_mr(existing_mr_url)
            print(f"  closed MR: {existing_mr_url}", flush=True)
        except Exception as e:
            print(f"  could not close MR (continuing): {e}", flush=True)

    existing_branch = (app_row or {}).get("resume_draft_branch")
    if existing_branch:
        try:
            _delete_branch(existing_branch)
            print(f"  deleted branch: {existing_branch}", flush=True)
        except Exception as e:
            print(f"  could not delete branch (continuing): {e}", flush=True)

    apps_module.set_draft_pending(UUID(job_id))

    try:
        _run_generate_drafts(UUID(job_id), detail, "us.anthropic.claude-sonnet-5")
        print(f"  OK", flush=True)
    except Exception as e:
        print(f"  FAILED: {e}", flush=True)

    print(flush=True)

print("Done.", flush=True)
