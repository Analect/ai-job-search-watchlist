FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_CACHE_DIR=/tmp/uv-cache
# Disable the Bedrock SDK instrumentor — it crashes on guardrail metrics when
# traceloop runs with metrics disabled (guardrail_activation is None).
# Anthropic-level spans are still captured by the Anthropic instrumentor.
ENV OTEL_PYTHON_DISABLED_INSTRUMENTATIONS=bedrock

RUN uv pip install --system --no-cache --link-mode copy --reinstall \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "strands-agents[openai]>=1.52.0" \
    "mcp>=1.0.0" \
    "boto3>=1.34.0" \
    "amp-instrumentation" \
    "requests" \
    "wrapt==1.17.3"

COPY instrumentation.py prompt.md tools.py agent.py ./

RUN useradd --no-create-home --shell /bin/false agent && chown -R agent:agent /app
USER agent

EXPOSE 8080

# amp-instrument wraps uvicorn with zero-code OTel tracing.
# AMP injects AMP_OTEL_ENDPOINT and AMP_AGENT_API_KEY at runtime.
CMD ["amp-instrument", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8080"]
