# ai-job-search-watchlist

A personal job-search watchlist platform: per-ATS-type ingest
pipelines, a Postings/Discovery-map web app, and an MCP server, all
deployed as OpenChoreo Components on the `openchoreo-caipe-platform`
Hetzner K3s cluster.

Full specification, design, and task breakdown live in the
`ai-platform-eng-lab` repo:
`specs/015-ai-job-search-watchlist/` (`spec.md`, `plan.md`,
`research.md`, `data-model.md`, `contracts/`, `tasks.md`,
`quickstart.md`).

## Layout

```text
pipelines/
  adapters/      # one fetch_postings() module per ATS type
  common/        # shared: db, scrape_runs, closure, location_normalize,
                 # events (mark_for_advancement), similarity (find_similar)
  enrichment/    # embeddings (Bedrock Titan v2), key_terms
mcp_server/      # job-search-mcp: search_jobs/get_job_detail/
                 # mark_for_advancement/find_similar over Streamable HTTP
api/             # job-search-api (FastAPI): /postings, /map, /watchlist
web/             # job-search-web (React/Vite/TS/Tailwind)
notebooks/       # marimohub project content: query prototyping + analysis
db/migrations/   # job_search Postgres schema
tests/adapters/  # per-ATS-type adapter unit tests (recorded fixtures)
```

## Status

See `tasks.md` in the spec repo for the authoritative task list and
progress. This repo was an empty shell as of 2026-09-04.
