# job-search-api (015-ai-job-search-watchlist). Build context is the
# REPO ROOT (not this directory) — api/app.py imports pipelines.common.*
# (postings.py, events.py, similarity.py, db.py), same shared-module
# layout reasoning as pipelines/Dockerfile.
FROM ghcr.io/typst/typst:latest AS typst-bin
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
COPY --from=typst-bin /usr/local/bin/typst /usr/local/bin/typst
WORKDIR /app
ENV UV_CACHE_DIR=/tmp/uv-cache
ENV PYTHONUNBUFFERED=1
RUN uv pip install --system --no-cache --link-mode copy --reinstall \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "psycopg2-binary>=2.9" \
    "scikit-learn>=1.5" \
    "umap-learn>=0.5" \
    "boto3>=1.34" \
    "requests>=2.31" \
    "opentelemetry-sdk>=1.25" \
    "opentelemetry-exporter-otlp-proto-http>=1.25"
COPY pipelines/common/ pipelines/common/
COPY pipelines/__init__.py pipelines/__init__.py
COPY api/ api/
RUN python -c "import api.app"
EXPOSE 8000
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
