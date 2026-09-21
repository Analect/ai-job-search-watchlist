"""job-search-api: the direct (non-assistant) path for the job search watchlist.

017-enhanced-job-search adds:
  - New event vocabulary (reviewed/flag_on/flag_off/promoted/withdrawn/
    thumbs_*/comment_updated) routed through the single write path in
    events.py + applications.py (T005).
  - POST /postings/bulk-review (T010).
  - Updated GET /postings review_state filter (T017).
  - GET /jobs/map/coordinates (T021), GET /jobs/promoted (T022).
  - GET /employers/{slug}/similar (T024), GET /map/dendrogram (T025).
  - DELETE /watchlist/{slug} (T032).
  - GET /applications (T035), POST /applications/{id}/status (T036).
  - POST /applications/{id}/generate-drafts (T039).

No auth logic lives here — the platform gateway validates the caller's
identity before any request reaches this Component.
"""

import os
from contextlib import asynccontextmanager
from uuid import UUID

import requests

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from api.job_map_projection import get_job_projection
from api.map_projection import get_dendrogram, get_projection
from pipelines.common import applications as apps_module
from pipelines.common.applications import AlreadyActiveError, update_notes
from pipelines.common.db import get_connection
from pipelines.common.employer_similarity import find_similar_employers
from pipelines.common.events import VALID_EVENT_TYPES, mark_for_advancement
from pipelines.common.postings import (
    bulk_mark_reviewed,
    get_job_detail,
    list_postings,
    list_unreviewed_for_employer,
)
from pipelines.common.similarity import find_similar
from pipelines.common.watchlist import add_to_watchlist, remove_from_watchlist
from api.drafting import AVAILABLE_DRAFT_MODELS, DraftAlreadyMergedError, _delete_branch, close_mr, generate_drafts, generate_pdf, get_draft_files, merge_draft, update_draft_files
from pipelines.enrichment.promoted_enrichment import enrich_promoted

# OTel tracing — only initialised when OTEL_EXPORTER_OTLP_ENDPOINT is set so
# local dev without a collector doesn't spin up a background export thread.
_OTEL_ENABLED = bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
if _OTEL_ENABLED:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    _provider = TracerProvider(
        resource=Resource({SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", "job-search-api")})
    )
    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    _otel_trace.set_tracer_provider(_provider)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm both projection caches during pod startup so the first real
    # request doesn't hit a cold UMAP computation (504 risk — same fix
    # already applied for the employer map, now extended to the job map).
    get_projection()
    get_job_projection()
    yield


app = FastAPI(title="job-search-api", lifespan=lifespan)


class PostingEventRequest(BaseModel):
    event_type: str
    note: str | None = None


class BulkReviewRequest(BaseModel):
    posting_ids: list[str]


class ApplicationStatusRequest(BaseModel):
    status: str


class ApplicationNotesRequest(BaseModel):
    notes: str | None = None


class GenerateDraftsRequest(BaseModel):
    model_id: str | None = None


@app.get("/draft-models")
def get_draft_models() -> dict:
    return {"models": AVAILABLE_DRAFT_MODELS}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


def _db_ok() -> bool:
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("select 1")
            cur.fetchone()
        return True
    except Exception:
        return False


@app.get("/readyz")
def readyz() -> dict:
    return {"db": "ok" if _db_ok() else "unreachable"}


@app.get("/admin/scrape-health")
def get_scrape_health(threshold: int = Query(default=3, ge=1)) -> dict:
    """Return employers whose last N consecutive successful scrape runs all
    yielded zero postings, indicating a potential adapter or config issue."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select e.slug, e.name, e.consecutive_zero_postings,
                   e.last_successful_run_at
              from employers e
             where e.consecutive_zero_postings >= %s
             order by e.consecutive_zero_postings desc, e.name
            """,
            (threshold,),
        )
        rows = cur.fetchall()
    return {
        "threshold": threshold,
        "employers": [
            {
                "slug": r[0],
                "name": r[1],
                "consecutive_zero_postings": r[2],
                "last_successful_run_at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ],
    }


@app.get("/postings")
def get_postings(
    location: str | None = Query(default=None, pattern="^(london|dublin|other)$"),
    status: str | None = Query(default=None, pattern="^(open|closed)$"),
    review_state: str | None = Query(
        default=None,
        pattern="^(unreviewed|reviewed|flagged|promoted|thumbs_up|thumbs_down)$",
    ),
    query: str | None = None,
    company: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return list_postings(
        location=location,
        status=status,
        review_state=review_state,
        query=query,
        company=company,
        limit=limit,
        offset=offset,
    )


# POST /postings/bulk-review must be declared BEFORE /postings/{posting_id}
# so FastAPI doesn't try to match "bulk-review" as a UUID.
@app.post("/postings/bulk-review")
def post_bulk_review(body: BulkReviewRequest) -> dict:
    updated = bulk_mark_reviewed(body.posting_ids)
    return {"updated": updated}


@app.get("/postings/{posting_id}")
def get_posting_detail(posting_id: UUID) -> dict:
    detail = get_job_detail(posting_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="posting not found")
    return detail


@app.post("/postings/{posting_id}/events")
def post_posting_event(posting_id: UUID, body: PostingEventRequest, background_tasks: BackgroundTasks) -> dict:
    if body.event_type not in VALID_EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"invalid event_type: {body.event_type!r}")

    detail = get_job_detail(posting_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="posting not found")

    posting = detail["posting"]

    if body.event_type == "promoted":
        try:
            apps_module.create_or_reactivate(posting_id)
        except AlreadyActiveError as e:
            raise HTTPException(status_code=422, detail=str(e))
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "update job_postings set promoted = true where id = %s", (str(posting_id),)
            )
            conn.commit()
        background_tasks.add_task(enrich_promoted, posting_id)

    elif body.event_type == "withdrawn":
        if not posting.get("promoted"):
            raise HTTPException(
                status_code=422,
                detail="posting is not currently promoted; cannot withdraw",
            )
        result = apps_module.withdraw(posting_id)
        if result is None:
            raise HTTPException(status_code=404, detail="no application found for this posting")
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "update job_postings set promoted = false where id = %s", (str(posting_id),)
            )
            conn.commit()

    return mark_for_advancement(posting_id, body.event_type, source="user", note=body.note)


@app.get("/postings/{posting_id}/similar")
def get_similar_postings(posting_id: UUID, limit: int = Query(default=5, ge=1, le=50)) -> dict:
    if get_job_detail(posting_id) is None:
        raise HTTPException(status_code=404, detail="posting not found")
    return find_similar(job_posting_id=posting_id, limit=limit)


# --- Employer map / watchlist ---

@app.get("/map/coordinates")
def get_map_coordinates() -> dict:
    return {"companies": get_projection()}


@app.get("/map/dendrogram")
def get_map_dendrogram() -> dict:
    return get_dendrogram()


@app.post("/watchlist/{slug}")
def post_watchlist(slug: str) -> dict:
    result = add_to_watchlist(slug)
    if result is None:
        raise HTTPException(status_code=404, detail="company not found")
    return result


@app.delete("/watchlist/{slug}")
def delete_watchlist(slug: str) -> dict:
    result = remove_from_watchlist(slug)
    if result is None:
        raise HTTPException(status_code=404, detail="company not found")
    return result


@app.get("/employers/{slug}/similar")
def get_similar_employers(slug: str, limit: int = Query(default=5, ge=1, le=20)) -> dict:
    return find_similar_employers(slug, limit=limit)


@app.get("/employers/{slug}/postings")
def get_employer_postings(slug: str) -> dict:
    return {"results": list_unreviewed_for_employer(slug)}


# --- Job map / promoted list ---

@app.get("/jobs/map/coordinates")
def get_job_map_coordinates() -> dict:
    return {"jobs": get_job_projection()}


@app.get("/jobs/promoted")
def get_promoted_jobs() -> dict:
    return list_postings(review_state="promoted", limit=500, offset=0)


# --- Applications ---

@app.get("/applications")
def get_applications() -> dict:
    results = apps_module.list_all()
    return {"results": results}


@app.patch("/applications/{job_posting_id}/notes")
def patch_application_notes(job_posting_id: UUID, body: ApplicationNotesRequest) -> dict:
    result = update_notes(job_posting_id, body.notes)
    if result is None:
        raise HTTPException(status_code=404, detail="no application found for this posting")
    return result


@app.post("/applications/{job_posting_id}/status")
def post_application_status(job_posting_id: UUID, body: ApplicationStatusRequest) -> dict:
    try:
        result = apps_module.advance_status(job_posting_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="no application found for this posting")
    return result


@app.post("/applications/{job_posting_id}/generate-drafts")
def post_generate_drafts(
    job_posting_id: UUID, background_tasks: BackgroundTasks,
    body: GenerateDraftsRequest = GenerateDraftsRequest(),
) -> JSONResponse:
    # Idempotent: return complete state if draft already exists.
    existing = apps_module.get_draft_info(job_posting_id)
    if existing:
        return JSONResponse(status_code=200, content={
            "status": "complete",
            "resume_draft_branch": existing["resume_draft_branch"],
            "resume_draft_mr_url": existing["resume_draft_mr_url"],
            "resume_draft_path": existing["resume_draft_path"],
            "cover_letter_draft_path": existing["cover_letter_draft_path"],
            "draft_generated_at": existing["draft_generated_at"],
        })

    app_row = apps_module.get(job_posting_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="no application found for this posting")

    # Already pending — background task still running.
    if app_row["status"] == "drafting":
        return JSONResponse(status_code=202, content={"status": "pending"})

    detail = get_job_detail(job_posting_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="posting not found")
    if detail.get("description") is None:
        raise HTTPException(
            status_code=422,
            detail="cannot draft: no job description captured for this posting",
        )

    apps_module.set_draft_pending(job_posting_id)
    background_tasks.add_task(_run_generate_drafts, job_posting_id, detail, body.model_id)
    return JSONResponse(status_code=202, content={"status": "pending"})


def _run_generate_drafts(job_posting_id: UUID, detail: dict, model_id: str | None = None) -> None:
    try:
        draft = generate_drafts(job_posting_id, detail, model_id=model_id)
        apps_module.persist_draft_info(
            job_posting_id,
            branch=draft["resume_draft_branch"],
            mr_url=draft["resume_draft_mr_url"],
            resume_path=draft["resume_draft_path"],
            cover_letter_path=draft["cover_letter_draft_path"],
            generated_at=draft["draft_generated_at"],
            model_id=draft.get("draft_model_id"),
            trace_id=draft.get("draft_trace_id"),
        )
    except Exception as e:
        apps_module.set_draft_failed(job_posting_id, str(e))


@app.get("/applications/{job_posting_id}/draft-status")
def get_draft_status(job_posting_id: UUID) -> dict:
    result = apps_module.get_draft_status(job_posting_id)
    if result is None:
        raise HTTPException(status_code=404, detail="no application found for this posting")
    return result


@app.get("/applications/{job_posting_id}/trace")
def get_application_trace(job_posting_id: UUID) -> dict:
    """Return OTel spans for the LLM draft generation call from OpenSearch."""
    draft = apps_module.get_draft_info(job_posting_id)
    if draft is None or not draft.get("draft_trace_id"):
        raise HTTPException(status_code=404, detail="no trace on record for this application")

    trace_id = draft["draft_trace_id"]
    os_url = os.environ.get("OPENSEARCH_URL", "").rstrip("/")
    os_user = os.environ.get("OPENSEARCH_USERNAME", "")
    os_pass = os.environ.get("OPENSEARCH_PASSWORD", "")
    if not os_url:
        raise HTTPException(status_code=503, detail="OpenSearch credentials not configured")

    try:
        resp = requests.post(
            f"{os_url}/otel-traces-*/_search",
            auth=(os_user, os_pass),
            json={
                "size": 50,
                "query": {"term": {"traceId": trace_id}},
                "_source": True,
            },
            timeout=10,
            verify=False,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"OpenSearch error: {exc}")

    hits = resp.json().get("hits", {}).get("hits", [])
    spans = [h["_source"] for h in hits]
    return {"trace_id": trace_id, "spans": spans}


@app.get("/applications/{job_posting_id}/draft-files")
def get_application_draft_files(job_posting_id: UUID) -> dict:
    draft = apps_module.get_draft_info(job_posting_id)
    if draft is None or not draft.get("resume_draft_mr_url"):
        raise HTTPException(status_code=404, detail="no draft on record for this application")
    try:
        return get_draft_files(
            draft["resume_draft_branch"],
            draft["resume_draft_path"],
            draft["cover_letter_draft_path"],
        )
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GitLab API error: {exc}")


@app.get("/applications/{job_posting_id}/draft-pdf")
def get_draft_pdf(
    job_posting_id: UUID,
    file: str = Query(default="resume", pattern="^(resume|cover_letter)$"),
) -> Response:
    draft = apps_module.get_draft_info(job_posting_id)
    if draft is None or not draft.get("resume_draft_branch"):
        raise HTTPException(status_code=404, detail="no draft on record for this application")

    path_key = "resume_draft_path" if file == "resume" else "cover_letter_draft_path"
    draft_path = draft.get(path_key)
    if not draft_path:
        raise HTTPException(status_code=404, detail="draft path not found")

    try:
        pdf_bytes = generate_pdf(draft["resume_draft_branch"], draft_path)
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GitLab API error: {exc}")
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    filename = "resume.pdf" if file == "resume" else "cover_letter.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


class DraftFilesBody(BaseModel):
    resume: str
    cover_letter: str


@app.patch("/applications/{job_posting_id}/draft-files")
def patch_application_draft_files(job_posting_id: UUID, body: DraftFilesBody) -> dict:
    draft = apps_module.get_draft_info(job_posting_id)
    if draft is None or not draft.get("resume_draft_mr_url"):
        raise HTTPException(status_code=404, detail="no draft on record for this application")
    try:
        return update_draft_files(
            draft["resume_draft_branch"],
            draft["resume_draft_path"],
            draft["cover_letter_draft_path"],
            body.resume,
            body.cover_letter,
        )
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GitLab API error: {exc}")


@app.post("/applications/{job_posting_id}/draft-merge")
def post_draft_merge(job_posting_id: UUID) -> dict:
    draft = apps_module.get_draft_info(job_posting_id)
    if draft is None or not draft.get("resume_draft_mr_url"):
        raise HTTPException(status_code=404, detail="no draft on record for this application")
    try:
        result = merge_draft(draft["resume_draft_mr_url"])
    except DraftAlreadyMergedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GitLab merge failed: {exc}")
    apps_module.advance_status(job_posting_id, "submitted")
    return {"status": "submitted", "final_url": result["final_url"]}


@app.post("/applications/{job_posting_id}/redraft")
def post_redraft(
    job_posting_id: UUID, background_tasks: BackgroundTasks,
    body: GenerateDraftsRequest = GenerateDraftsRequest(),
) -> JSONResponse:
    app_row = apps_module.get(job_posting_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="no application found for this posting")

    detail = get_job_detail(job_posting_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="posting not found")
    if detail.get("description") is None:
        raise HTTPException(
            status_code=422,
            detail="cannot redraft: no job description captured for this posting",
        )

    existing_mr_url = app_row.get("resume_draft_mr_url")
    if existing_mr_url:
        try:
            close_mr(existing_mr_url)
        except requests.HTTPError:
            pass  # already closed/merged — proceed anyway

    existing_branch = app_row.get("resume_draft_branch")
    if existing_branch:
        try:
            _delete_branch(existing_branch)
        except Exception:
            pass  # best-effort; branch may not exist

    apps_module.set_draft_pending(job_posting_id)
    background_tasks.add_task(_run_generate_drafts, job_posting_id, detail, body.model_id)
    return JSONResponse(status_code=202, content={"status": "pending"})
