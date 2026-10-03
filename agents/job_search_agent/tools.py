"""MCP tool loader for the Job Search Agent.

Connects to the job-search-mcp-xplatform MCP server (5 tools) via the
AMP MCP Proxy (MCP_PROXY_URL) or the direct internal gateway when the
proxy URL is not yet configured.

The default URL uses the bare gateway-internal hostname (no ExternalName
alias) — the job-search HTTPRoute on gateway-internal matches PathPrefix
/mcp without a hostname restriction, acting as the default route when
no more-specific hostname-qualified route matches.

strands-agents >= 1.52 accepts MCPClient(url=..., headers=...) directly as a
ToolProvider — no custom transport or context manager required.

Environment variables:
  MCP_PROXY_URL  — gateway URL for the MCP proxy (from AMP console)
  MCP_PROXY_KEY  — API key header value for the MCP proxy (from ExternalSecret)
"""
import os

from strands.tools.mcp import MCPClient

_DEFAULT_MCP_URL = (
    "http://gateway-internal.openchoreo-data-plane.svc.cluster.local:9080/mcp"
)


def mcp_url() -> str:
    return os.environ.get("MCP_PROXY_URL") or _DEFAULT_MCP_URL


def mcp_headers() -> dict[str, str]:
    key = os.environ.get("MCP_PROXY_KEY", "")
    return {"API-Key": key} if key else {}


def make_mcp_client() -> MCPClient:
    headers = mcp_headers()
    return MCPClient(url=mcp_url(), headers=headers or None)
