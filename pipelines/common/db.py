"""Shared job_search Postgres connection, used by every adapter, the
enrichment pass, api/app.py, and mcp_server/server.py.

The DSN comes from JOB_SEARCH_PG_DSN, populated at deploy time from
Vault (secret/supabase/postgres, per constitution §II and
research.md §10/T007) via each OpenChoreo Component's Trait, or set
directly in a local .env for development.

Fallback: when JOB_SEARCH_PG_DSN is absent, _build_dsn_from_pg_env()
assembles a DSN from the standard libpq env vars (PGHOST, PGPORT,
PGDATABASE, PGUSER, PGPASSWORD). marimohub's PostgreSQL integration
injects exactly these names by default (ambient_env=on), which unlocks
Option B in-cluster notebook sessions (docs/marimo/in-cluster-notebooks.md)
without any changes to the marimohub project's Vault wiring.
"""

import os

import psycopg2
import psycopg2.extensions

_ENV_VAR = "JOB_SEARCH_PG_DSN"


def _build_dsn_from_pg_env() -> str | None:
    host = os.environ.get("PGHOST")
    if not host:
        return None
    parts = [f"host={host}"]
    if port := os.environ.get("PGPORT"):
        parts.append(f"port={port}")
    if dbname := os.environ.get("PGDATABASE"):
        parts.append(f"dbname={dbname}")
    if user := os.environ.get("PGUSER"):
        parts.append(f"user={user}")
    if password := os.environ.get("PGPASSWORD"):
        parts.append(f"password={password}")
    return " ".join(parts)


def get_connection() -> psycopg2.extensions.connection:
    dsn = os.environ.get(_ENV_VAR) or _build_dsn_from_pg_env()
    if not dsn:
        raise RuntimeError(
            f"{_ENV_VAR} is not set — see pipelines/common/db.py and "
            "research.md §10 for the Vault-sourced DSN convention."
        )
    return psycopg2.connect(dsn)


def get_dlt_destination():
    """dlt's native postgres destination, sharing the same DSN
    convention as get_connection() (research.md §1/§9)."""
    import dlt

    dsn = os.environ.get(_ENV_VAR) or _build_dsn_from_pg_env()
    if not dsn:
        raise RuntimeError(f"{_ENV_VAR} is not set — see pipelines/common/db.py.")
    return dlt.destinations.postgres(credentials=dsn)
