# job-search-mcp (015-ai-job-search-watchlist, T054-T058). Build
# context is the REPO ROOT (not this directory) — server.py imports
# pipelines.common.* (postings.py, events.py, similarity.py, db.py),
# same shared-module layout reasoning as api/Dockerfile.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_CACHE_DIR=/tmp/uv-cache
ENV PYTHONUNBUFFERED=1
RUN uv pip install --system --no-cache --link-mode copy --reinstall \
    "mcp>=2.0" \
    "uvicorn[standard]>=0.30" \
    "psycopg2-binary>=2.9"
COPY pipelines/common/ pipelines/common/
COPY pipelines/__init__.py pipelines/__init__.py
COPY mcp_server/ mcp_server/
RUN python -c "import mcp_server.server"
EXPOSE 8000
CMD ["uvicorn", "mcp_server.server:app", "--host", "0.0.0.0", "--port", "8000"]
