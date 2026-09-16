# marimohub push-sync from GitLab CI

## What was set up

A GitLab CI job (`sync-marimohub` in `.gitlab-ci.yml`) runs on every merge
to `main` and POSTs the repository archive to the marimohub push-sync API.
This means notebooks in the repo are automatically available in marimohub
after each push, without any manual upload step.

### CI job (`.gitlab-ci.yml`)

```yaml
sync-marimohub:
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  image: alpine:latest
  before_script:
    - apk add --no-cache curl tar gzip git
  script:
    - git archive --format=tar.gz -o /tmp/sync.tgz HEAD
    - |
      curl --fail-with-body -X POST "$MARIMOHUB_SYNC_URL" \
        -H "Authorization: Bearer $MARIMOHUB_SYNC_TOKEN" \
        -H "Content-Type: application/gzip" \
        -H "X-Marimohub-Archive-Format: tar.gz" \
        -H "X-Marimohub-Repo: $CI_PROJECT_PATH" \
        -H "X-Marimohub-Branch: main" \
        -H "X-Marimohub-Root-Path: " \
        -H "X-Marimohub-Commit: $CI_COMMIT_SHA" \
        --data-binary @/tmp/sync.tgz
  variables:
    GIT_DEPTH: "1"
```

`git archive` is used (not `tar czf .`) because plain tar produces `./`-prefixed
entries that the marimohub sync API rejects as unsafe paths.

### CI variables (set in GitLab project settings)

| Variable | Value |
|---|---|
| `MARIMOHUB_SYNC_URL` | `https://marimohub-development.apps.oc.analect.com/api/sync/git/v1/projects/proj-qv6zdhd7hz6nebfm/notebooks/nb-pr2gg8p9qe096m5b` |
| `MARIMOHUB_SYNC_TOKEN` | (secret — set once, shown only on notebook creation) |

The notebook (`nb-pr2gg8p9qe096m5b`, title "Pharma analysis") was created via
the marimohub API before the first sync. The sync token was generated at
creation time.

### `.gitattributes`

`uv.lock export-ignore` excludes the lockfile from `git archive` output.
The lockfile encodes the full dev-machine dependency graph (including
platform-specific wheels) and causes uv to fail in the sandbox when present.

### `pyproject.toml` — slim core deps

Heavy ML and server packages were moved to optional extras so that
`uv sync --inexact` in the sandbox only needs to install lightweight deps:

```
core (default): psycopg2-binary, pandas, requests
[ml]:           scikit-learn, scipy, umap-learn
[pipelines]:    dlt[postgres], boto3
[server]:       mcp, fastapi, uvicorn
[dev]:          pytest, ruff
```

Local development: `uv sync --extra ml --extra pipelines --extra server --extra dev`

## Sync is one-way

GitLab → marimohub only. Changes made inside marimohub (editing cells,
saving the notebook) do not flow back to GitLab. The repo is the source of
truth; marimohub is the run environment.

`git archive` excludes `.git`, so multi-file session publishing (write-back
from marimohub to the repo) is not available. This was a deliberate trade-off
to keep the archive clean and small.

## Impasse: `pipelines.common` not importable in sandbox

![ModuleNotFoundError in marimohub](images/job-search-marimo-pipelines-common-error.png)

### Root cause

`pipelines` is a local package in this repo (not on PyPI). For
`from pipelines.common.db import get_connection` to work, either:

- the project must be installed as an editable package (so `pipelines/` is on
  `sys.path` via a `.pth` file in site-packages), or
- the project root must be added to `sys.path` before the import runs.

### What was tried

**`package = true` (default uv behaviour)** — uv runs `uv sync` and installs
the project as a wheel. This requires building via `hatchling` (the
`[build-system]`). This *was* working locally but fails in the marimohub
sandbox with `uv exited unsuccessfully`. The exact uv error is not surfaced by
marimohub's UI. Likely causes: the sandbox Python version, missing build
toolchain, or network restrictions during wheel build.

**`[tool.uv] package = false`** — tells uv to skip installing the project
itself; only the listed dependencies are installed. uv sync succeeds and the
notebook opens. However, `pipelines/` is not on `sys.path`, so
`import pipelines.common` raises `ModuleNotFoundError` at cell runtime.
marimo's pre-run package checker also flags it before cells execute.

**`sys.path` manipulation in a notebook cell** — adding the project root to
`sys.path` inside an imports cell runs too late: marimo's static package
check fires before any cell executes and shows the "Missing packages" dialog.
Even if that dialog is dismissed, cell execution order in marimo means the
sys.path cell may not run before the import cell.

### Notes from marimohub API docs (`docs/syncing.md`)

The docs state:

> If the synced root contains `pyproject.toml`, `uv sync --inexact` adds its
> dependencies to the base environment. **If this command fails, the session
> continues with the base environment.**

This means `uv sync` failure via `pyproject.toml` is documented as **non-fatal**.
Yet marimohub is surfacing "Failed to prepare the notebook Python environment:
uv exited unsuccessfully" as a fatal blocking error. The syncing docs are
explicitly flagged as "work in progress, no backwards-compatibility guarantee",
so this may reflect a behaviour change not yet reflected in the docs. Worth
raising with marimohub.

### Options not yet tried

1. **Inspect the actual uv error** — `kubectl exec` into the sandbox pod and
   run `uv sync --inexact` manually to see the real error. The marimohub UI
   only surfaces the exit code. The actual failure reason (Python version
   mismatch, hatchling build failure, network restriction, etc.) would be
   definitive and point to the right fix.

2. **Switch build backend to `setuptools`** — setuptools is more likely to be
   pre-installed in the sandbox than hatchling. Replace `[build-system]` with
   `requires = ["setuptools>=61"]` / `build-backend = "setuptools.build_meta"`
   and add `[tool.setuptools.packages.find]`. May unblock `package = true`
   if hatchling availability is the actual cause.

3. **`PYTHONPATH` env var** — if marimohub exposes environment variable
   injection at the project or notebook level, setting
   `PYTHONPATH=/workspace` (or wherever the archive root is extracted) would
   make `import pipelines` work without any wheel build. Worth checking the
   marimohub project settings UI.

4. **Publish `pipelines` to a private PyPI registry** — publish to the GitLab
   Package Registry PyPI index and add it as a normal versioned dep. Cleanest
   long-term solution; removes all editable-install complexity entirely.

## Multiple notebooks

There is no project-level sync endpoint. Each notebook in marimohub has its
own sync URL and token. To sync multiple notebooks from the same CI job, POST
the same archive to each sync URL:

```yaml
script:
  - git archive --format=tar.gz -o /tmp/sync.tgz HEAD
  - |
    for URL in $MARIMOHUB_SYNC_URL_PHARMA $MARIMOHUB_SYNC_URL_QUERIES; do
      curl --fail-with-body -X POST "$URL" ...
    done
```

At scale, storing N tokens as GitLab CI variables is unwieldy. The better
pattern is to store all tokens in Vault under one path as a JSON object (e.g.
`secret/marimohub/sync-tokens`) and have CI fetch them once and loop.
