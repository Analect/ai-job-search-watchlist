"""job-search-mcp: the assistant-facing path for FR-018/019/020
(mcp-server-tools.contract.md).

Every tool here wraps a shared `pipelines/common/*` function — never a
parallel/reimplemented query — so the assistant path and the direct
`job-search-api` path stay provably consistent (research.md §11):
- search_jobs / get_job_detail -> pipelines/common/postings.py
- mark_for_advancement -> pipelines/common/events.py (source='assistant')
- find_similar -> pipelines/common/similarity.py

Streamable HTTP transport (research.md §8) — `stdio` is confirmed
broken in this cluster's dynamic-agents image. No auth logic lives
here: AgentGateway's own Keycloak-JWT + OpenFGA `can_call mcp:server`
enforcement establishes the caller's identity before any request
reaches this server (FR-020, single-user platform per spec
Assumptions) — same convention as api/app.py.

mcp>=1.0 resolves to mcp 2.x today, where `mcp.server.fastmcp.FastMCP`
(what every earlier design note was written against) was renamed to
`mcp.server.mcpserver.MCPServer` — confirmed live via the real
installed package, not assumed from the version pin.
"""

from uuid import UUID

from mcp.server.mcpserver import MCPServer

from pipelines.common.events import mark_for_advancement as _mark_for_advancement
from pipelines.common.postings import get_job_detail as _get_job_detail
from pipelines.common.postings import search_jobs as _search_jobs
from pipelines.common.similarity import find_similar as _find_similar

mcp = MCPServer(name="job-search-mcp")


@mcp.tool()
def search_jobs(
    query: str | None = None,
    location: str | None = None,
    company: str | None = None,
    status: str | None = "open",
    limit: int = 20,
) -> dict:
    """Search current watchlist postings by free text, location
    (london/dublin/other), employer name, and status (defaults to
    open). Returns an explicit message when nothing matched, never a
    bare empty list."""
    return _search_jobs(
        query=query, location=location, company=company, status=status, limit=limit
    )


@mcp.tool()
def get_job_detail(id: str) -> dict:
    """Full detail on one posting by id: all fields, its captured
    description, and its complete job_events history."""
    try:
        posting_id = UUID(id)
    except ValueError:
        return {"error": f"{id!r} is not a valid posting id"}
    detail = _get_job_detail(posting_id)
    if detail is None:
        return {"error": f"no posting found with id {id!r}"}
    return detail


@mcp.tool()
def mark_for_advancement(id: str, note: str | None = None) -> dict:
    """Mark a posting as worth advancing — the same event log
    job-search-web's Postings page writes to (source='assistant' here
    vs 'user' there), so it's one consistent history either way.
    Calling this twice on the same posting is intentional, not an
    error: each call is its own history row."""
    try:
        posting_id = UUID(id)
    except ValueError:
        return {"error": f"{id!r} is not a valid posting id"}
    if _get_job_detail(posting_id) is None:
        return {"error": f"no posting found with id {id!r}"}
    return _mark_for_advancement(
        posting_id, "flagged_for_advancement", source="assistant", note=note
    )


@mcp.tool()
def find_similar(id: str | None = None, limit: int = 5) -> dict:
    """Find postings genuinely similar in substance to a given one
    (defaults to the most recently flagged-for-advancement posting if
    id is omitted). Only open postings are candidates. Returns an
    explicit message rather than an empty list when nothing has ever
    been flagged and no id was given."""
    posting_id: UUID | None = None
    if id is not None:
        try:
            posting_id = UUID(id)
        except ValueError:
            return {"error": f"{id!r} is not a valid posting id"}
    return _find_similar(job_posting_id=posting_id, limit=limit)


app = mcp.streamable_http_app(stateless_http=True)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
