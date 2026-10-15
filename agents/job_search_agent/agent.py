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
  LLM_PROVIDER_URL    — LlmProxy gateway-runtime URL (OpenAI-compatible endpoint).
                        When set, routes LLM calls through the AMP gateway.
                        When absent, falls back to Bedrock direct.
  LLM_PROVIDER_KEY    — API key for the LLM provider
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

LLM_PROVIDER_URL = os.environ.get("LLM_PROVIDER_URL", "")
LLM_PROVIDER_KEY = os.environ.get("LLM_PROVIDER_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "us.anthropic.claude-sonnet-4-6")


def _build_model():
    if LLM_PROVIDER_URL:
        from strands.models.openai import OpenAIModel
        log.info("LLM: AMP provider at %s model=%s", LLM_PROVIDER_URL, LLM_MODEL)
        return OpenAIModel(
            client_args={"api_key": LLM_PROVIDER_KEY, "base_url": LLM_PROVIDER_URL},
            model_id=LLM_MODEL,
        )
    from strands.models import BedrockModel
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    log.info("LLM: Bedrock direct model=%s region=%s", LLM_MODEL, region)
    return BedrockModel(model_id=LLM_MODEL, region_name=region)


app = FastAPI(title="Job Search Agent", version="1.0.0")


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
        mcp_client = make_mcp_client()
        agent = Agent(
            model=_build_model(),
            tools=[mcp_client],
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
