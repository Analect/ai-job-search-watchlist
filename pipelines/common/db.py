"""Shared job_search Postgres connection, used by every adapter, the
enrichment pass, api/app.py, and mcp_server/server.py.

The DSN comes from JOB_SEARCH_PG_DSN, populated at deploy time from
Vault (secret/supabase/postgres, per constitution §II and
research.md §10/T007) via each OpenChoreo Component's Trait, or set
directly in a local .env for development.
"""

import os

import psycopg2
import psycopg2.extensions

_ENV_VAR = "JOB_SEARCH_PG_DSN"


def get_connection() -> psycopg2.extensions.connection:
    dsn = os.environ.get(_ENV_VAR)
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

    dsn = os.environ.get(_ENV_VAR)
    if not dsn:
        raise RuntimeError(f"{_ENV_VAR} is not set — see pipelines/common/db.py.")
    return dlt.destinations.postgres(credentials=dsn)
