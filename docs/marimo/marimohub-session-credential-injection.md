# marimohub session credential injection

## Why the ClusterTrait/ClusterResource pattern cannot reach session sandboxes

Every env var injected via `envBindings` in a Component's `workload.yaml` —
and every output of the `marimohub-auth` or `marimohub-seaweedfs-storage`
ClusterResourceTypes — lands in the **marimohub-server container's
environment**. That is the Node.js server pod running in the
`dp-analect-marimohub-development` namespace.

Session sandbox pods are a completely separate concern. marimohub-server
spawns them dynamically in the `marimo-kernels` namespace when a user opens a
notebook. What goes into those pods' environments is controlled exclusively by
**marimohub's integrations system**: credentials are stored encrypted in
SeaweedFS (using `MARIMOHUB_SECRETS_KEK`), and the server reads them at
session-start time to inject into each sandbox pod's env.

There is no `MARIMOHUB_COMPUTE_KUBERNETES_EXTRA_ENV` or similar pass-through
parameter in the CRT that would let server env vars flow into kernel pods. This
boundary is architectural — marimohub deliberately keeps integration credentials
out of the server process's own environment so that a compromise of the server
does not expose every project's database credentials to the attacker. The KEK
(which the server does hold) allows decryption of stored integration configs,
but only at session-provision time and only into the sandboxed pod.

```
  marimohub-auth CRT outputs
  (Vault → ESO → K8s Secret)
         │
         ▼
  marimohub-server pod env          ← ClusterResourceType / ClusterTrait reach stops here
  (OIDC, storage, compute config)
         │
         │  spawns at session open
         ▼
  marimo-kernels namespace
  ┌────────────────────────────┐
  │  Session sandbox pod       │
  │                            │
  │  env injected by:          │
  │  marimohub integrations    │  ← only path into sandbox env
  │  system (SeaweedFS-backed) │
  └────────────────────────────┘
```

## The three options for injecting JOB_SEARCH_PG_DSN into notebook sessions

### Option 1 — marimohub UI / API (inline encrypted)

Add a PostgreSQL or Environment Variables integration to the
`marimohub-poweruser` project through the UI or the marimohub REST API.
The credential is pasted in once, encrypted at rest with `MARIMOHUB_SECRETS_KEK`,
and stored in SeaweedFS. marimohub injects it into every subsequent session.

No GitOps file carries the credential. One-time configuration; persists across
restarts. The integration can also be created via API:

```bash
curl -X POST https://marimohub-poweruser-development.apps.oc.analect.com/api/v1/projects/{pid}/integrations \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "environment_variables",
    "name": "job-search-db",
    "config": {
      "secret_variables": [
        { "name": "JOB_SEARCH_PG_DSN", "value": "<dsn-from-vault>" }
      ]
    }
  }'
```

### Option 2 — db.py PGHOST fallback (already implemented)

marimohub's PostgreSQL integration injects `PGHOST`, `PGPORT`, `PGDATABASE`,
`PGUSER`, `PGPASSWORD` by default (`ambient_env=on`). `pipelines/common/db.py`
now falls back to constructing a DSN from these when `JOB_SEARCH_PG_DSN` is
absent. Configure the marimohub project's PostgreSQL integration pointing at
the Supabase instance (one-time UI step or API call). `db.py` picks it up
automatically with no further changes.

This also makes the connection discoverable in marimo's data-source panel.

### Option 3 — Kubernetes secret backend (fully GitOps, recommended)

marimohub's `k8s` secret backend allows integration secret fields to reference
a Kubernetes Secret by name and key, resolved at session-start time. Combined
with ESO pulling from Vault, the full chain is GitOps-managed with no
credentials in any file and no UI involvement after initial setup.

#### Architecture

```
Vault: secret/supabase/job-search (property: database_url_external)
    │
    │  ESO ExternalSecret (same pattern as job-search-db-credentials ClusterTrait)
    ▼
K8s Secret: analect/supabase-job-search-credentials
  label: marimohub.io/integration-secret: 'true'   ← required opt-in
    │
    │  marimohub k8s secret resolver
    │  (MARIMOHUB_SECRETS_KUBERNETES=true, allowed in MARIMOHUB_SECRETS_KUBERNETES_ALLOWED_SECRETS)
    ▼
marimohub integration (environment_variables kind)
  JOB_SEARCH_PG_DSN → { "$secret": { "kind": "reference", "backend": "k8s",
                          "locator": "analect/supabase-job-search-credentials#dsn" } }
    │
    │  injected at session start
    ▼
Session sandbox pod: JOB_SEARCH_PG_DSN=postgres://...
```

#### What needs to be built

**Step 1 — ExternalSecret in `openchoreo-flux-state`** ✓ built

`namespaces/analect/projects/marimohub/resources/supabase-job-search-externalsecret.yaml`

Syncs `database_url_external` from `secret/supabase/job-search` (same Vault
path as the `job-search-db-credentials` ClusterTrait) into a K8s Secret named
`supabase-job-search-credentials` in `dp-analect-marimohub-development-5f006ab8`
(the runtime namespace for the marimohub project — consistent with the other
hand-authored ExternalSecrets there). The Secret carries the required
`marimohub.io/integration-secret: 'true'` label both on the ExternalSecret
resource and on the target Secret via the ESO template.

Also added to `resources/kustomization.yaml` alongside the companion RBAC file.

**Step 1b — RBAC for the k8s resolver** ✓ built

`namespaces/analect/projects/marimohub/resources/supabase-job-search-rbac.yaml`

The marimohub-server pod runs as the `default` ServiceAccount in
`dp-analect-marimohub-development-5f006ab8` (confirmed in the existing
`marimo-kernels/rolebinding.yaml`). Pods do not automatically have `get` access
to Secrets in their own namespace. A namespace-scoped Role + RoleBinding grants
exactly `get` on `supabase-job-search-credentials` and nothing else, mirroring
the pattern marimohub's Helm chart would create automatically.

**Step 2 — Enable the k8s resolver in `marimohub-auth` CRT** ✓ built

`platform-shared/cluster-resource-types/marimohub-auth.yaml`

Two new parameters added (defaulting to off/empty so no existing deployment
is affected):

```yaml
secrets_kubernetes:          # default: "false"
secrets_kubernetes_allowed_secrets:  # default: "[]"
```

Two corresponding outputs (`MARIMOHUB_SECRETS_KUBERNETES`,
`MARIMOHUB_SECRETS_KUBERNETES_ALLOWED_SECRETS`) added to the CRT outputs list.

`envBindings` entries for both variables added to
`components/marimohub-server/workload.yaml` and
`components/marimohub-poweruser/workload.yaml`.

**Step 3 — Enable the resolver on `marimohub-auth-poweruser` Resource** ✓ built

`resources/marimohub-auth-poweruser.yaml`

```yaml
secrets_kubernetes: "true"
secrets_kubernetes_allowed_secrets: >-
  [{"namespace":"dp-analect-marimohub-development-5f006ab8","name":"supabase-job-search-credentials","projects":"*"}]
```

Note: the namespace is `dp-analect-marimohub-development-5f006ab8`, not
`analect` — the Secret lives in the marimohub pod's own runtime namespace,
consistent with the other hand-authored ExternalSecrets for this project.

**Step 4 — Register the integration (one-time API call)** ⏳ pending deploy

Once marimohub-poweruser is redeployed with the resolver enabled, register the
integration via API (scriptable; no UI required). The locator uses the actual
namespace where the Secret lives:

```bash
curl -X POST https://marimohub-poweruser-development.apps.oc.analect.com/api/v1/projects/{pid}/integrations \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "environment_variables",
    "name": "job-search-db",
    "config": {
      "secret_variables": [
        {
          "name": "JOB_SEARCH_PG_DSN",
          "value": {
            "$secret": {
              "kind": "reference",
              "backend": "k8s",
              "locator": "dp-analect-marimohub-development-5f006ab8/supabase-job-search-credentials#dsn"
            }
          }
        }
      ]
    }
  }'
```

This step stores the *reference* (not the credential value) in SeaweedFS.
The actual DSN is resolved from the Kubernetes Secret at each session start.
Vault rotation flows through ESO → K8s Secret → session sandbox automatically,
with no integration update needed.

#### Why this is preferred over Options 1 and 2

- Vault remains the single source of truth for the credential, consistent with
  every other component in this platform (`job-search-db-credentials` ClusterTrait
  uses the identical Vault path and property).
- No credential ever appears in a GitOps file or an API request body.
- Rotation in Vault propagates to new sessions automatically (ESO refreshes the
  K8s Secret every 15 minutes; running sessions keep the value they received at
  startup, per marimohub's documented behaviour).
- The integration registration (Step 4) is a one-time bootstrap that survives
  marimohub restarts and redeployments — the integration record lives in
  SeaweedFS alongside notebook versions and other project state.

## db.py fallback (belt-and-suspenders)

Regardless of which option is used to inject the DSN, `pipelines/common/db.py`
now falls back to constructing a connection string from `PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD` when `JOB_SEARCH_PG_DSN` is absent. This
means a marimohub PostgreSQL integration (Option 2) also works without any
additional configuration, and the notebooks remain usable if the Environment
Variables integration is ever misconfigured or missing.
