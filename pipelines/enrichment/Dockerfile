# enrichment-pipeline (015-ai-job-search-watchlist, T040-T042). Separate
# image from pipelines/Dockerfile (the 8 ATS adapters' shared image) —
# boto3/scikit-learn/numpy are heavier deps none of those need. Build
# context is the REPO ROOT (not this directory), same reasoning as
# pipelines/Dockerfile: shares pipelines/common/.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_CACHE_DIR=/tmp/uv-cache
ENV PYTHONUNBUFFERED=1
RUN uv pip install --system --no-cache --link-mode copy --reinstall \
    "psycopg2-binary>=2.9" \
    "boto3>=1.34" \
    "scikit-learn>=1.5"
COPY pipelines/ pipelines/
RUN python -c "import pipelines.common.db, pipelines.enrichment.embeddings, pipelines.enrichment.key_terms, pipelines.enrichment_pipeline"
