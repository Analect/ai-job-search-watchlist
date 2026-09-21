# ai-job-search-watchlist

A personal job-search platform running entirely on the
`openchoreo-caipe-platform` Hetzner K3s cluster: per-ATS ingest
pipelines, a postings/discovery web app, an MCP server for the CAIPE
assistant, and an AI drafting pipeline that produces tailored typst
resumes and cover letters committed to a private GitLab repo.

Full specification and task history: `ai-platform-eng-lab` repo at
`specs/015-ai-job-search-watchlist/` and
`specs/018-drafting-quality-improvements/`.

---

## What it does

```
 Nine ATS APIs          In-cluster (OpenChoreo)         Your browser
 (Greenhouse,     -->   ingest pipelines      -->   Postings / Discovery
  Lever, Workday,       enrichment pipeline            web app
  Ashby, …)            job-search-api
                        job-search-mcp          -->   CAIPE Job Search
                                                       Agent
                        job-search-api          -->   AI draft  -->  GitLab MR
                         (Bedrock Claude)               in mccoole/resume
```

1. **Ingests** job postings directly from nine ATS platforms' own APIs
   — no scraping, no third-party aggregator.
2. **Enriches** postings with embeddings (Titan v2), key terms
   (TF-IDF for all; Bedrock structured extraction for promoted
   postings), and a cosine-similarity index used for "find similar"
   queries.
3. **Serves** them through a gateway-fronted React app: postings list
   with review-state tracking and full-text search; employer proximity
   map (~2,700 companies); watchlist; and an Applications tab for
   promoted postings.
4. **Drafts** tailored resumes and cover letters via AWS Bedrock
   (Claude). Drafts are committed to a branch in `mccoole/resume` and
   opened as a merge request for human review.
5. **Exposes** the same data to a CAIPE dynamic agent
   (`job-search-mcp`) for conversational queries.

---

## Codebase layout

```
cli/
  jsw                   # command-line client (see below)
pipelines/
  adapters/             # one fetch_postings() per ATS type
  common/               # db, events, applications, similarity, closure, …
  enrichment/           # Titan v2 embeddings, TF-IDF key_terms,
                        #   promoted_enrichment (Bedrock structured extraction)
mcp_server/             # job-search-mcp: search_jobs / get_job_detail /
                        #   mark_for_advancement / find_similar
api/
  app.py                # FastAPI routes
  drafting.py           # Bedrock draft generation + clean-prose pass
web/                    # React / Vite / TypeScript / Tailwind SPA
notebooks/              # marimohub analysis notebooks
  promoted_jd_analysis.py   # interactive JD analysis (read-only, no Bedrock)
db/migrations/          # Postgres schema — apply in numeric order
tests/                  # per-adapter unit tests (recorded HTTP fixtures)
```

---

## Interface with `mccoole/resume`

The drafting pipeline (`api/drafting.py`) reads from and writes to the
`mccoole/resume` GitLab repository at runtime. Three folders matter:

```
mccoole/resume/
  system/
    why-what-how-system.md      # voice & framing rules  →  Bedrock system param
    pillars-career-arc-system.md # career positioning     →  Bedrock system param
    candidate-profile.md        # factual ground truth   →  user turn (authoritative)

  projects/
    *.md                        # one file per notable project / initiative
                                # all fetched and injected into the user turn
                                # ranked by cosine similarity to the target role
                                # ADD new files here to improve project matching

  analysis/
    scripts/
      promoted_jd_analysis.py  # two-phase analysis script (run in-cluster)
    promoted-jd-analysis.md    # latest output — 8 themes, 25 promoted roles
```

### How prompts are assembled

```
  system parameter
  ├── system/why-what-how-system.md
  ├── system/pillars-career-arc-system.md
  └── [hard override rule: Candidate Profile is authoritative for all facts]

  user turn
  ├── system/candidate-profile.md   (## Candidate Profile — authoritative)
  ├── job description text
  ├── typst/templates/resume-template.typ
  ├── typst/templates/letter-template.typ
  ├── projects/*.md                 (## Candidate Project Portfolio)
  └── per-application notes (if any)

  → Bedrock response (typst source for resume + letter)
  → clean-prose pass (second Bedrock call via clean_prose_prompt.md)
  → commit to branch + open MR
```

The project files in `projects/` are ranked by cosine similarity
against the role's extracted intelligence (key terms, responsibilities,
requirements — **not** the full JD text). Add new `projects/*.md`
files to improve draft relevance for future roles.

---

## Enrichment on promotion

When a posting is promoted to the Applications tab, an async Bedrock
call extracts structured intelligence and stores it in Postgres:

```
  POST /postings/{id}/events  {"event_type": "promoted"}
         │
         └── BackgroundTask: promoted_enrichment.py
               ├── Bedrock → { key_terms[], responsibilities[], requirements[] }
               ├── job_postings.key_terms   text[]
               ├── job_postings.enrichment  jsonb
               └── job_postings.embedding   vector(1024)  ← Titan v2 on intelligence text
```

The embedding of the extracted intelligence (not the full JD) is what
the drafting pipeline uses to rank candidate `projects/` files.

---

## Running analysis against live data (in-cluster)

The `job-search-api` pod has both database and AWS Bedrock credentials
in scope. Use `kubectl exec -i` to pipe scripts directly into it:

```bash
# Set your kubeconfig
export KUBECONFIG=~/.kube/config-oc-platform

# Get the pod name
NS=$(kubectl get ns -o name | grep dp-analect-ai-job-search-development | cut -d/ -f2)
POD=$(kubectl get pod -n $NS -l app=job-search-api-development -o name | head -1 | cut -d/ -f2)

# Run the promoted JD analysis (Phase 1: aggregate + Phase 2: Bedrock clustering)
# Output: promoted-jd-analysis.md in mccoole/resume/analysis/
kubectl exec -i -n $NS $POD -- \
  python - < analysis/scripts/promoted_jd_analysis.py \
  > /path/to/mccoole/resume/analysis/promoted-jd-analysis.md

# Run the enrichment backfill (safe to re-run — idempotent)
kubectl exec -i -n $NS $POD -- \
  python -c "from pipelines.enrichment.promoted_enrichment import backfill_promoted; backfill_promoted()"
```

The analysis script runs in two phases:
- **Phase 1** — frequency tables of key terms, full responsibility and
  requirement lists, per-role key term breakdown
- **Phase 2** — Bedrock Claude clusters the full input into 6–9
  addressable themes with project guidance (uses streaming to avoid
  read timeouts on large prompts)

Use the output to decide which new `projects/*.md` files to write in
`mccoole/resume`.

---

## Command-line client (`cli/jsw`)

`cli/jsw` is a standalone Python script (requires only `requests`,
already a project dependency). It calls the `job-search-api` over
HTTP — the API is behind the OpenChoreo gateway, so either
port-forward first or point it at the gateway's external URL.

### Setup

```bash
# Option A: port-forward (no cluster auth required beyond kubeconfig)
kubectl port-forward -n $NS svc/job-search-api-development 8080:8080 &
export JSW_API_URL=http://localhost:8080

# Option B: gateway external URL (if exposed)
export JSW_API_URL=https://job-search-api.your-gateway-domain.com

# Put the script on your PATH
ln -sf $(pwd)/cli/jsw ~/.local/bin/jsw
```

### Commands

```
jsw list [options]           list postings
jsw show ID|URL              show one posting by UUID or ATS source URL
jsw promote ID|URL           promote a posting (triggers async enrichment)
jsw draft ID|URL             trigger AI draft generation
jsw draft-status ID|URL      check draft generation status
jsw applications             list all promoted applications
```

#### `jsw list` — browse and filter postings

```bash
jsw list                                 # latest 25 postings
jsw list --state unreviewed --limit 50   # unreviewed only
jsw list --state promoted                # your application pipeline
jsw list --location london --query mlops # filtered by city + keyword
jsw list --company openai                # all postings from one employer
jsw list --status open --limit 100 --offset 25  # pagination
```

Output:
```
S  ID                                    Employer                 Title                                     City    Posted      Status
-  ------------------------------------  -----------------------  ----------------------------------------  ------  ----------  ------
★  3a8f1c2d-…                           Anthropic                Staff ML Engineer                         London  2026-09-18  open
⚑  7b2e4a9f-…                           Palantir Technologies    Senior Software Engineer, AI Platform     London  2026-09-17  open
↑  c1d3f7a2-…                           DeepMind                 Research Engineer                         London  2026-09-15  open
```

State icons: `★` promoted · `⚑` flagged · `↑` thumbs up · `↓` thumbs down · `✓` reviewed

#### `jsw show` — inspect a posting

```bash
# By UUID
jsw show 3a8f1c2d-0000-0000-0000-000000000000

# By pasting the ATS URL directly from your browser
jsw show "https://boards.greenhouse.io/anthropic/jobs/1234567"
```

#### `jsw promote` — promote from the command line

```bash
jsw promote 3a8f1c2d-0000-0000-0000-000000000000
jsw promote "https://boards.greenhouse.io/anthropic/jobs/1234567" \
  --note "Strong alignment with agentic AI theme from JD analysis"
```

Promotion creates an Application row and triggers async Bedrock
enrichment in the background (key terms, responsibilities,
requirements, intelligence embedding).

#### `jsw draft` — trigger AI draft generation

```bash
jsw draft 3a8f1c2d-0000-0000-0000-000000000000
jsw draft 3a8f1c2d-… --model us.anthropic.claude-opus-5
jsw draft --list-models          # see available Bedrock model IDs

# Check status (generation runs in the background)
jsw draft-status 3a8f1c2d-…
```

Draft generation fetches system and project docs from `mccoole/resume`,
assembles the prompt, calls Bedrock, applies the clean-prose pass, and
commits the result to a new branch + MR. The MR URL is shown once
`draft-status` reports `drafting`.

---

## Key operational commands

```bash
# List all OpenChoreo components in the project
kubectl get component -n analect

# Watch enrichment pipeline logs
kubectl logs -n $NS -l app=enrichment-pipeline-development -f

# Check all kustomization health (Flux)
kubectl get kustomization -A

# Restart the API pod (e.g. after a code change via image rebuild)
kubectl rollout restart deployment/job-search-api-development -n $NS
```

---

## Status

Feature `015-ai-job-search-watchlist` shipped the core ingestion,
discovery, watchlist, and MCP integration.
Feature `018-drafting-quality-improvements` added the enrichment
pipeline, Metadata drawer, intelligence-based project ranking,
clean-prose pass, and local OTel trace storage.
See `tasks.md` files in the corresponding spec directories for the
full task log.
