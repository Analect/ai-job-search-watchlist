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

### Options not yet tried

1. **`PYTHONPATH` env var on the marimohub project/notebook** — if marimohub
   lets you set environment variables at project level, setting
   `PYTHONPATH=/workspace` (or wherever the archive root lands) would make
   `import pipelines` work without any pyproject changes. Worth checking the
   marimohub project settings UI.

2. **A `.pth` file in site-packages** — a one-liner file placed in
   `site-packages/` at sandbox startup would add the project root permanently.
   Cannot be done from the archive directly; would need a marimohub hook or
   init script.

3. **Switch build backend to `setuptools`** — setuptools is more likely to be
   pre-installed in the sandbox than hatchling. Replace `[build-system]` with
   `requires = ["setuptools>=61"]` / `build-backend = "setuptools.build_meta"`
   and add `[tool.setuptools.packages.find]`. May unblock the `package = true`
   path if hatchling is the actual uv failure cause.

4. **Inspect the actual uv error** — the marimohub sandbox pod logs (or a
   `kubectl exec` into the sandbox pod) would show the real uv output. With
   that, the root cause of the wheel-build failure would be definitive.

5. **Publish `pipelines` to a private PyPI registry** — if the internal
   GitLab Package Registry or a Gitea/Nexus PyPI index is available, publish
   `pipelines` there and add it as a normal versioned dependency. Cleanest
   long-term solution; avoids all editable-install complexity.
