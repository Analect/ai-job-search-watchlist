"""Job Search Agent — OpenChoreo proxy/ai-agent (A2 Flux variant).

FastAPI server implementing the AMP external-agent chat interface. Wraps a
Strands agent with 5 tools from job-search-mcp-xplatform via the AMP MCP
Proxy (or direct internal gateway as fallback).

AMP instrumentation is zero-code: the Dockerfile CMD uses `amp-instrument uvicorn`
so traces are captured without any code changes. The only prerequisite is setting
OTEL_SEMCONV_STABILITY_OPT_IN before strands is imported, which instrumentation.py
handles.

Environment variables (injected via ExternalSecret from
secret/openchoreo/job-search-agent-flux, plus AMP-injected OTEL vars):
  LLM_PROVIDER_URL    — AMP egress-gateway or OpenAI-compatible endpoint URL.
                        When set, routes LLM calls through the AMP gateway via ABSK.
                        When absent, falls back to Bedrock direct via IAM credentials.
  LLM_PROVIDER_KEY    — API key for the LLM provider
  LLM_GATEWAY_FORMAT  — "bedrock" (default) or "openai". Controls how LLM_PROVIDER_URL
                        is called. AMP egress gateways (port 22893) use Bedrock Converse
                        format; set to "openai" for OpenAI-compatible endpoints.
  LLM_MODEL           — model identifier (default: us.anthropic.claude-sonnet-4-6)
  MCP_PROXY_URL       — AMP MCP Proxy endpoint for job-search-mcp-xplatform
  MCP_PROXY_KEY       — API key header value for the MCP proxy
  AMP_OTEL_ENDPOINT   — AMP OTLP collector endpoint (injected by AMP)
  AMP_AGENT_API_KEY   — AgentID key for OTel span attribution (injected by AMP)
  AWS_ACCESS_KEY_ID   — Bedrock fallback (from aws-bedrock-credentials trait)
  AWS_SECRET_ACCESS_KEY
  AWS_DEFAULT_REGION  — default: us-east-1
"""
import instrumentation  # noqa: F401 — sets OTEL_SEMCONV_STABILITY_OPT_IN before strands

import logging
import os
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from strands import Agent

from tools import make_mcp_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [job-search-agent] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

SYSTEM_PROMPT = Path("prompt.md").read_text()

# generate-workload-cr may use legacy names (LLM_PROVIDER_URL/LLM_PROVIDER_KEY) or
# component-prefixed names ({COMPONENT_UPPER}_LLM_CONFIG_URL/_LLM_CONFIG_API_KEY).
LLM_PROVIDER_URL = os.environ.get("LLM_PROVIDER_URL") or next(
    (v for k, v in os.environ.items() if k.endswith("_LLM_CONFIG_URL") and v), ""
)
LLM_PROVIDER_KEY = os.environ.get("LLM_PROVIDER_KEY") or next(
    (v for k, v in os.environ.items() if k.endswith("_LLM_CONFIG_API_KEY") and v), ""
)
LLM_MODEL = os.environ.get("LLM_MODEL", "us.anthropic.claude-sonnet-4-6")
LLM_GATEWAY_FORMAT = os.environ.get("LLM_GATEWAY_FORMAT", "bedrock")


def _build_model():
    if LLM_PROVIDER_URL:
        if LLM_GATEWAY_FORMAT == "openai":
            # OpenAI-compatible endpoint (e.g. AMP AI gateway port 22895).
            # AMP egress gateway also requires X-API-Key alongside Authorization: Bearer.
            from strands.models.openai import OpenAIModel
            log.info("LLM: OpenAI-compat provider at %s model=%s", LLM_PROVIDER_URL, LLM_MODEL)
            return OpenAIModel(
                client_args={
                    "api_key": LLM_PROVIDER_KEY,
                    "base_url": LLM_PROVIDER_URL,
                    "default_headers": {"X-API-Key": LLM_PROVIDER_KEY},
                },
                model_id=LLM_MODEL,
            )
        # Default: AMP egress gateway (port 22893) is a Bedrock Converse proxy authenticated
        # via X-API-Key (ABSK). Use BedrockModel with an unsigned boto3 session that injects
        # X-API-Key before each request; the gateway handles its own Bedrock SigV4 auth.
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
        from strands.models import BedrockModel

        _key = LLM_PROVIDER_KEY

        def _inject_absk(request, **kwargs):
            request.headers["X-API-Key"] = _key

        session = boto3.Session(aws_access_key_id="dummy", aws_secret_access_key="dummy")
        session.events.register("before-send.bedrock-runtime.*", _inject_absk)
        log.info("LLM: AMP Bedrock proxy at %s model=%s", LLM_PROVIDER_URL, LLM_MODEL)
        return BedrockModel(
            model_id=LLM_MODEL,
            boto_session=session,
            boto_client_config=Config(signature_version=UNSIGNED),
            endpoint_url=LLM_PROVIDER_URL,
        )
    from strands.models import BedrockModel
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    log.info("LLM: Bedrock direct model=%s region=%s", LLM_MODEL, region)
    return BedrockModel(model_id=LLM_MODEL, region_name=region)


app = FastAPI(title="Job Search Agent", version="1.0.0")

# Initialized once at startup — avoids a fresh MCP TCP connection + tool load on
# every request, which caused per-request timeouts and init failures under load.
_MODEL = _build_model()
_MCP_CLIENT = make_mcp_client()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent": "job-search-agent-flux"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    session_id = req.session_id or str(uuid.uuid4())
    log.info("session=%s message_len=%d", session_id, len(req.message))

    try:
        agent = Agent(
            model=_MODEL,
            tools=[_MCP_CLIENT],
            system_prompt=SYSTEM_PROMPT,
            callback_handler=None,
        )
        result = agent(req.message)
    except Exception as exc:
        log.exception("agent invocation failed", extra={"session_id": session_id})
        raise HTTPException(status_code=500, detail="agent invocation failed") from exc

    log.info("session=%s response_len=%d", session_id, len(str(result)))
    return ChatResponse(response=str(result), session_id=session_id)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
