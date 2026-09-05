# Shared image for all 9+1 ingest pipelines (015-ai-job-search-watchlist).
# One image, many Components — each Component's workload.yaml overrides
# `args` to point at a different pipelines/<type>_pipeline.py entrypoint
# (matches synthetic-wealth-adviser's own workload.yaml override pattern).
#
# Build context is the REPO ROOT (not this directory) since adapters share
# pipelines/common/ and pipelines/adapters/ — a single pipeline.py-only
# context (SWA's per-pipeline convention) doesn't fit this repo's shared-
# module layout.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_CACHE_DIR=/tmp/uv-cache
# Unbuffered stdout — container logs are piped, not a TTY, so Python
# fully-buffers by default and progress prints only surface at exit.
ENV PYTHONUNBUFFERED=1
RUN uv pip install --system --no-cache --link-mode copy --reinstall \
    "dlt[postgres]>=1.22.0" \
    "psycopg2-binary>=2.9" \
    "requests>=2.31"
COPY pipelines/ pipelines/
# Validates the shared-module import chain (adapters -> common -> db/events/
# similarity) without hand-maintaining an import list — build fails here if
# anything is missing, same reasoning as SWA's own Dockerfile comment.
RUN python -c "import pipelines.common.db, pipelines.common.events, pipelines.common.similarity, pipelines.common.closure, pipelines.common.location_normalize, pipelines.common.scrape_runs, pipelines.common.http_retry"
