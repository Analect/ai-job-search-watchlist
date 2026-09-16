# In-cluster notebook access for ai-job-search-watchlist

## Background

The analysis notebooks in `notebooks/` (e.g. `pharma_analysis.py`,
`query_prototypes.py`) import from `pipelines.common` and need
`JOB_SEARCH_PG_DSN` to reach Supabase. Running them locally requires either a
WireGuard tunnel to the Supabase VM or a manually-pasted DSN — both ruled out
as a standing workflow. This document compares the two viable in-cluster paths.

---

## Option A — Standalone OpenChoreo Component (`job-search-notebooks`)

Add a dedicated `deployment/service` Component to the `ai-job-search-watchlist`
project in `openchoreo-flux-state`, mirroring the pattern used by
`swa-exploration` in the `synthetic-wealth-adviser` project.

### How it works

```
  Your browser                cluster
  ───────────                 ──────────────────────────────────────────────
  https://job-search-          dp-analect-ai-job-search-watchlist-development
  notebooks-development.  ──► ┌──────────────────────────────────────────┐
  apps.oc.analect.com          │  job-search-notebooks pod                │
  (Envoy Gateway TLS)          │  image: ghcr.io/analect/                 │
                               │    ai-job-search-watchlist/notebooks:... │
                               │                                          │
                               │  CMD: marimo edit                        │
                               │    --host 0.0.0.0 --port 2718            │
                               │    --no-token notebooks/                 │
                               │                                          │
                               │  ENV (from job-search-db-credentials     │
                               │  Trait via Vault):                       │
                               │    JOB_SEARCH_PG_DSN=postgres://...      │
                               │                                          │
                               │  /app/pipelines/common/   ← installed    │
                               │  /app/notebooks/          ← committed    │
                               └──────────────────────────────────────────┘
                                               │
                                               ▼
                                        Supabase Postgres
                                        (10.100.0.1:5432,
                                         in-cluster route)
```

### What needs to be built

1. **`notebooks/Dockerfile`** — new file (neither `pipelines/Dockerfile` nor
   `api/Dockerfile` includes `notebooks/` or `marimo`):

   ```dockerfile
   FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
   WORKDIR /app
   ENV UV_CACHE_DIR=/tmp/uv-cache
   ENV PYTHONUNBUFFERED=1
   RUN uv pip install --system --no-cache --link-mode copy --reinstall \
       "marimo>=0.24" \
       "psycopg2-binary>=2.9" \
       "pandas>=2.0" \
       "scikit-learn>=1.5" \
       "umap-learn>=0.5"
   COPY pipelines/ pipelines/
   COPY notebooks/ notebooks/
   RUN python -c "import pipelines.common.db"
   EXPOSE 2718
   CMD ["marimo", "edit", "--host", "0.0.0.0", "--port", "2718", \
        "--no-token", "--no-skew-protection", "notebooks/"]
   ```

2. **`openchoreo-flux-state` files** — three new files in
   `namespaces/analect/projects/ai-job-search-watchlist/components/job-search-notebooks/`:
   - `component.yaml` — `dockerfile-builder` workflow, `notebooks/Dockerfile`,
     `job-search-db-credentials` Trait only (no Bedrock/OpenSearch needed)
   - `workload.yaml` — port 2718, external visibility, `basePath`
   - `release-binding` — standard development binding

3. **Commit `notebooks/`** to the repo before the first build so the Dockerfile
   `COPY notebooks/` step has content.

### AI pairing from Claude Code

Once the component is live, pair on a running notebook from your workstation
with `marimo-pair` exactly as you would locally, but pointing at the cluster
URL. The `--no-token` flag means no `MARIMO_TOKEN` is needed. The `--url` flag
bypasses auto-discovery:

```bash
bash .claude/skills/marimo-pair/scripts/execute-code.sh \
  --url https://job-search-notebooks-development.apps.oc.analect.com \
  -c "import marimo._code_mode as cm; ..."
```

No WebSocket stand-in required — the external URL is reachable directly from
your browser and from Claude Code's Bash tool alike.

### Pros and cons

| | |
|---|---|
| ✓ | `pipelines.common` imports work — same image layout, no `sys.path` hacks |
| ✓ | `JOB_SEARCH_PG_DSN` injected by Vault via the existing Trait, zero manual credential plumbing |
| ✓ | Notebooks stay in the `ai-job-search-watchlist` repo, not duplicated anywhere |
| ✓ | No marimohub involvement — simpler ops surface, no session lifecycle concerns |
| ✓ | Pairability from Claude Code via `marimo-pair --url`, same skill, same workflow |
| ✗ | Requires a new `notebooks/Dockerfile` and image build cycle per change |
| ✗ | No native OpenCode AI chat panel inside the browser notebook UI |
| ✗ | The pod runs continuously (always-on cost), not session-gated like marimohub |

---

## Option B — marimohub-poweruser + OpenCode pairing

Use the existing `marimohub-poweruser` component
(`https://marimohub-poweruser-development.apps.oc.analect.com`) to host a
notebook session, with the OpenCode AI chat surface available alongside it in
the browser.

### Two notebook operating models in marimohub

marimohub supports two ways to get a notebook into a session:

**Model 1 — Object-store notebooks (manual upload)**
Notebooks are created or uploaded directly into marimohub's SeaweedFS-backed
storage (configured via the `s3` backend, confirmed in
`marimohub-seaweedfs-storage.yaml`). These live inside marimohub and are not
backed by a git repo. This is the model originally described here, and the one
that has the write-back discipline concern.

**Model 2 — Git-synced notebooks (source of truth in the git repo)**
marimohub can serve a notebook whose source of truth is an external Git
repository. Two sync modes:

| Mode   | How it syncs          | GitLab support | Write-back to repo |
| ------ | --------------------- | -------------- | ------------------ |
| `push` | CI uploads archive + sync token | Yes (GitLab CI job) | No native write-back — manual commit required |
| `pull` | marimohub pulls via GitHub App | GitHub.com only | Draft PR via GitHub App |

For the `ai-job-search-watchlist` repo (GitLab), only `push` mode is viable.
The GitLab CI job archives the repo tree and POSTs it to the marimohub sync
endpoint on each push to `main`. Each successful sync creates an immutable
version; **each session starts from a read-only copy of that version**. Session
edits do not change the stored version — the user must commit and push manually
before the session ends (or their edits are lost on sandbox teardown).

**Dependency installation from `pyproject.toml`**

This is the critical fact that changes the `pipelines.common` blocker: if the
synced root contains a `pyproject.toml`, marimohub runs `uv sync --inexact`
to add its dependencies to the base sandbox environment before the session
starts. Since the `ai-job-search-watchlist` repo has a `pyproject.toml` that
declares `pipelines` as an installable package, syncing the full repo (with
`root_path: ""`) would install `pipelines.common` automatically — no
`sys.path` hacks needed.

The revised architecture for Option B with git-sync:

```
  Your browser                          cluster
  ───────────                           ─────────────────────────────────────────
                                        dp-analect-marimohub-development
  https://marimohub-poweruser-    ────► ┌─────────────────────────────────────┐
  development.apps.oc.analect.com        │  marimohub-poweruser pod (Node.js)  │
  (Envoy Gateway TLS)                    │  manages session lifecycle          │
                                         └─────────────┬───────────────────────┘
                                                        │ provisions
                                                        ▼
                                         marimo-kernels namespace
                                        ┌─────────────────────────────────────┐
                                        │  Session pod (per session)           │
                                        │  image: ghcr.io/analect/marimohub/  │
                                        │    marimo-sandbox-opencode:v1-...    │
                                        │                                      │
                                        │  startup:                            │
                                        │    uv sync --inexact  ← pyproject.toml │
                                        │    (installs pipelines.common)       │
                                        │                                      │
                                        │  :2718  marimo kernel                │
                                        │  :4096  OpenCode AI surface          │
                                        │                                      │
                                        │  ENV (marimohub native postgres      │
                                        │  integration):                       │
                                        │    MARIMOHUB_PG_* / PGHOST / ...     │
                                        │    (NOT JOB_SEARCH_PG_DSN)           │
                                        │                                      │
                                        │  notebooks: read-only snapshot of    │
                                        │  latest git-synced version           │
                                        │  (stored in SeaweedFS S3 backend)    │
                                        └─────────────────────────────────────┘
                                                        │
                                                  GitLab CI push
                                                  (on every merge to main)
                                                        │
                                        ai-job-search-watchlist repo
                                        notebooks/pharma_analysis.py ←─── source of truth
```

### How it works

```
  Your browser                          cluster
  ───────────                           ─────────────────────────────────────────
                                        dp-analect-marimohub-development
  https://marimohub-poweruser-    ────► ┌─────────────────────────────────────┐
  development.apps.oc.analect.com        │  marimohub-poweruser pod (Node.js)  │
  (Envoy Gateway TLS)                    │  manages session lifecycle          │
                                         └─────────────┬───────────────────────┘
                                                        │ provisions
                                                        ▼
                                         marimo-kernels namespace
                                        ┌─────────────────────────────────────┐
                                        │  Session pod (per session)           │
                                        │  image: ghcr.io/analect/marimohub/  │
                                        │    marimo-sandbox-opencode:v1-...    │
                                        │                                      │
                                        │  :2718  marimo kernel                │
                                        │  :4096  OpenCode AI surface          │
                                        │                                      │
                                        │  ENV (marimohub native postgres      │
                                        │  integration):                       │
                                        │    MARIMOHUB_PG_* / PGHOST / ...     │
                                        │    (NOT JOB_SEARCH_PG_DSN)           │
                                        │                                      │
                                        │  notebooks: uploaded via UI or API   │
                                        │  (stored in SeaweedFS, ephemeral     │
                                        │   unless committed before teardown)  │
                                        └─────────────────────────────────────┘
                                                        │
                                         ┌──────────────┘
                                         ▼
                                  in-cluster KasmVNC browser
                                  (marimo-browser component)
                                  — needed to reach kernel-internal
                                    hostnames from a browser tab
```

### The blockers this approach requires working around

**1. `pipelines.common` — resolved by git-sync + `pyproject.toml`**

With git-sync (`push` mode, `root_path: ""`), marimohub runs
`uv sync --inexact` from the repo's `pyproject.toml` before the session starts.
This installs `pipelines` as a proper package, making
`from pipelines.common.db import get_connection` importable.

However, the `_onp-prior-marimo-pair.qmd` doc records a related bug found
during the `015` exercise:

> *"`pipelines.common` unimportable — `sys.path[0]` is the entry notebook's
> own directory, not the repo root — even after fixing the sync's `root_path`
> to include the whole repo"*

The `uv sync` path installs it as a proper Python package (not a path insert),
so this `sys.path[0]` issue should not apply — but this needs to be verified
end-to-end. If `pipelines` is not declared as a package in `pyproject.toml`
(e.g. no `[tool.uv.sources]` or similar pointing at the local `pipelines/`
directory), `uv sync --inexact` may install external deps but still not make
the local `pipelines/` tree importable.

**2. `JOB_SEARCH_PG_DSN` shape mismatch — resolved in `db.py`, credential injection path documented**

`db.py` now falls back to constructing a DSN from `PGHOST`/`PGPORT`/
`PGDATABASE`/`PGUSER`/`PGPASSWORD` when `JOB_SEARCH_PG_DSN` is absent, which
marimohub's PostgreSQL integration injects by default. The remaining step is
getting the Supabase credential into marimohub session sandboxes.

The CRT/ClusterTrait pattern **cannot** do this — it only reaches the
marimohub-server pod, not session sandboxes. Three options are documented in
`marimohub-session-credential-injection.md`. The recommended path (Option 3)
uses marimohub's `k8s` secret backend to reference a Kubernetes Secret that
ESO syncs from `secret/supabase/job-search` — the same Vault path already used
by the `job-search-db-credentials` ClusterTrait. This requires two CRT
parameter additions, one new ExternalSecret resource, and a one-time API call
to register the integration.

**3. Session write-back is not guaranteed**

The `_onp-known-gaps.qmd` doc records `SessionLifecycleService.sweep()` as
unresolved: AI-assisted edits are present in the kernel pod's local filesystem
but are not reliably captured to git on an unclean timeout. The safe practice
is to commit and push manually before ending a session.

### Write-back: GitLab has no native path, but a GitHub mirror unlocks it

marimohub's PR creation (publishing session edits back to the repo) works
through its GitHub App — GitHub.com only. For a GitLab source repo there are
two options:

**Manual round-trip (simplest)**: edit locally, commit, push to GitLab, GitLab
CI re-syncs to marimohub. Any in-session edits must be copied back manually
before the sandbox tears down.

**GitHub mirror + webhook (automated write-back)**: mirror the
`ai-job-search-watchlist` repo from GitLab to GitHub. Configure marimohub to
use the GitHub mirror for PR creation. When marimohub opens a PR on GitHub,
a webhook propagates it back to GitLab as an MR.

The critical loop-prevention requirement: GitLab's native push mirror is
one-way and destructive — it overwrites the GitHub mirror on every push. A PR
merged on the GitHub mirror will be wiped on the next mirror sweep unless the
write-back path is designed to avoid this. Two concrete patterns (with CI
snippets) are documented in `gitlab-github-interaction.md`:

- **Webhook-to-MR** (recommended): GitHub webhook fires when marimohub opens
  a PR → automation opens a parallel MR on the GitLab upstream → human reviews
  and merges on GitLab → changes flow to the GitHub mirror normally.
- **GitLab CI force-sync**: GitHub webhook fires on PR merge → triggers a
  GitLab CI pipeline that force-pulls from GitHub and pushes to GitLab with
  `ci.skip` to prevent a mirror loop.

The mirror approach requires: a GitHub mirror of the repo, a GitHub App
install on that mirror, a webhook receiver, and loop-prevention logic. It is
tractable but adds infrastructure complexity.

### AI pairing from Claude Code

The prior `015` proving exercise showed this is achievable but requires a
WebSocket stand-in process to hold the "editor connection" open while
`execute-code.sh --url` operates. Without it, every call returns *"No active
sessions — make sure a notebook is open."* The stand-in script exists (it was
built for that exercise) but adds operational friction compared to Option A.

### Pros and cons

| | |
|---|---|
| ✓ | Native OpenCode AI chat panel inside the browser notebook UI (no Claude Code needed for pairing) |
| ✓ | Session-gated compute — pod only runs while a session is active |
| ✓ | marimohub's Data browser (SQL runner, table explorer) available alongside the notebook |
| ✓ | Infrastructure already live and proven (`016-opencode-notebook-pairing`) |
| ✓ | Git-sync (`push` mode) keeps notebooks source-of-truth in `ai-job-search-watchlist` repo |
| ✓ | `pyproject.toml` auto-install via `uv sync --inexact` resolves `pipelines.common` imports |
| ✓ | `JOB_SEARCH_PG_DSN` mismatch resolved — `db.py` now falls back to `PGHOST`/`PGDATABASE`/`PGUSER`/`PGPASSWORD` |
| ✗ | Sessions are read-only snapshots — edits must be committed and pushed manually before teardown |
| ✗ | No native write-back to GitLab; marimohub PR creation requires GitHub App (GitHub only) |
| ✗/~ | Write-back via GitHub mirror is possible but non-trivial (see `gitlab-github-interaction.md`) |
| ✗ | Requires a new GitLab CI job to push the sync archive on merge to `main` |
| ✗ | Claude Code pairing requires a WebSocket stand-in process |
| ✗ | Uses KasmVNC in-cluster browser for kernel-internal hostnames (extra component dependency) |

---

## Comparison summary

| Factor | Option A (standalone component) | Option B (marimohub-poweruser) |
|---|---|---|
| `pipelines.common` imports | Works immediately (same image) | Resolved by `uv sync --inexact` — `pipelines` is declared in `pyproject.toml` |
| DB credentials | Vault Trait → `JOB_SEARCH_PG_DSN` (exact match) | PostgreSQL integration → `PGHOST`/etc. → `db.py` fallback (done); one-time UI config needed |
| Notebook location | `ai-job-search-watchlist` git repo (baked into image) | `ai-job-search-watchlist` git repo via push-mode sync (SeaweedFS = immutable versions) |
| AI pairing from Claude Code | `marimo-pair --url`, no stand-in needed | `marimo-pair --url` + WebSocket stand-in |
| In-browser AI chat | No (Claude Code only) | Yes (OpenCode surface) |
| Always-on cost | Pod runs continuously | Pod only runs during active session |
| New infrastructure needed | `notebooks/Dockerfile` + 3 GitOps files | GitLab CI sync job + `db.py` env-var fallback or new CRT param |
| Write-back safety | Committed on image build; edits ephemeral | No native GitLab write-back; GitHub mirror pattern enables PR flow (see `gitlab-github-interaction.md`) |

## Recommendation

For the immediate use case (pharma sector exploration, watchlist management),
**Option A** is still the lower-friction path to get running today.
`pipelines.common` and the credential shape work without modification, no new
GitLab CI job is needed, and the pairing workflow is simpler.

**Option B with git-sync** is now a more viable path than originally documented,
with one remaining hard blocker: `JOB_SEARCH_PG_DSN` vs. marimohub's native
`MARIMOHUB_PG_*` / `PGHOST` injection. The resolution options are:

- Adapt `pipelines/common/db.py` to fall back to `PGHOST` + `PGDATABASE` +
  `PGUSER` + `PGPASSWORD` when `JOB_SEARCH_PG_DSN` is absent (minimal change,
  backwards-compatible)
- Or add a custom env injection to the `marimohub-auth-poweruser` CRT

The `pyproject.toml` auto-install via `uv sync --inexact` resolves the
`pipelines.common` import issue. `pipelines` is declared as a top-level package
in `pyproject.toml` (`packages = ["api", "pipelines", "mcp_server"]`), so a
full-repo sync installs it as a proper importable package.

Choose **Option B** if the in-browser OpenCode chat experience is the goal and
you are willing to invest in the write-back infrastructure. The minimum viable
path for Option B without the GitHub mirror is: push-sync via GitLab CI +
manual commit discipline for write-back + configure the marimohub PostgreSQL
integration (the `db.py` env-var fallback is already in place).
The full write-back path (GitHub mirror + webhook) is documented in
`gitlab-github-interaction.md`.

Choose **Option A** if you want something working today with no new CI or
credential plumbing.

## Pre-requisite for both options

The notebooks must be committed to the `ai-job-search-watchlist` git repo
before either option is wired up. For Option A they need to be in the image.
For Option B they need to exist somewhere to be uploaded into a session
(manually or via API). Commit `notebooks/pharma_analysis.py` (and the existing
notebooks) as the first step either way.
