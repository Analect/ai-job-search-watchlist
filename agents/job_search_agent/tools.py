"""MCP tool loader for the Job Search Agent.

Connects to the job-search-mcp-xplatform MCP server (5 tools) via the
AMP MCP Proxy (MCP_PROXY_URL) or the direct internal gateway when the
proxy URL is not yet configured.

The MCP server uses stateless HTTP, so a fresh connection is made per
agent invocation.

The default URL uses the bare gateway-internal hostname (no ExternalName
alias) — the job-search HTTPRoute on gateway-internal matches PathPrefix
/mcp without a hostname restriction, acting as the default route when
no more-specific hostname-qualified route matches.

Environment variables:
  MCP_PROXY_URL  — gateway URL for the MCP proxy (from AMP console)
  MCP_PROXY_KEY  — API key header value for the MCP proxy (from ExternalSecret)
"""
import os

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp import MCPClient

_DEFAULT_MCP_URL = (
    "http://gateway-internal.openchoreo-data-plane.svc.cluster.local:9080/mcp"
)


def mcp_url() -> str:
    return os.environ.get("MCP_PROXY_URL") or _DEFAULT_MCP_URL


def mcp_headers() -> dict[str, str]:
    key = os.environ.get("MCP_PROXY_KEY", "")
    return {"API-Key": key} if key else {}


async def open_mcp_client():
    """Async context manager that yields a Strands MCPClient over streamable HTTP."""
    import contextlib

    @contextlib.asynccontextmanager
    async def _ctx():
        async with httpx2.AsyncClient(headers=mcp_headers()) as http_client:
            async with streamable_http_client(mcp_url(), http_client=http_client) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    yield MCPClient(lambda: session)

    return _ctx()
