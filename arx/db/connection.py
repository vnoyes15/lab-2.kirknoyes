"""Database session management.

Every query Arx runs on behalf of a request must run inside a Postgres session where
the `request.jwt.claims` GUC carries the caller's org_id and role — that's what the RLS
policies installed by arx_apply_org_rls() (arx/db/migrations/001_extensions_and_helpers.sql)
check on every table. This module is the single place that wires a request's identity
into that GUC, so MT1 ("Every agent context query includes org_id filter. Never pass
unfiltered data to an agent prompt.") holds structurally rather than by convention —
a query issued through db_session() cannot see another org's rows even if application
code forgets to add `WHERE org_id = ...` itself.

set_config(..., true) sets the value for the current transaction only (mirrors the
`is_local` semantics of `SET LOCAL`), so a pooled connection can never leak one
request's claims into the next.
"""
import json
from contextlib import contextmanager
from typing import Iterator

import psycopg
from fastapi import HTTPException
from psycopg.types.numeric import FloatLoader
from psycopg_pool import ConnectionPool

from arx.api.config import get_settings

_pool: ConnectionPool | None = None


def _configure_connection(conn: psycopg.Connection) -> None:
    # Postgres `numeric` loads as decimal.Decimal by default. Every agent schema
    # (Section 87) and validation suite (Section 15) works in plain float — a
    # Decimal quietly reaching arithmetic against a float (e.g. purchase_price * ltv)
    # raises TypeError instead of computing. Registering this once here, for every
    # connection the app pool hands out, is simpler and safer than remembering to
    # float() every numeric column at every call site.
    conn.adapters.register_loader("numeric", FloatLoader)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        # app_database_url, never database_url — see arx/api/config.py's field docs.
        # A superuser/BYPASSRLS connection here would make every RLS policy a no-op.
        _pool = ConnectionPool(
            settings.app_database_url, min_size=1, max_size=10, open=True,
            configure=_configure_connection,
        )
    return _pool


@contextmanager
def db_session(claims: dict | None = None) -> Iterator[psycopg.Connection]:
    """Yields a connection scoped to `claims` for the duration of one transaction.

    claims should contain at least {"org_id": ..., "role": ..., "sub": ...} — the same
    shape arx/api/auth.py verifies out of the request's bearer token. Pass claims=None
    only for platform-level operations that intentionally run outside any org's RLS
    scope (e.g. scripts/seed_org.py, which uses the Supabase service-role connection
    and bypasses RLS by design — never do this from request-handling code).

    HTTPException is deliberately special-cased: every agent endpoint's error path
    (arx/api/agents.py's _handle_agent_failure, the A08 suppressed/daily-limit
    branches, etc.) writes an error_log row (Section 10 EH4) or a notification inside
    this same connection's transaction and then raises HTTPException to return a
    structured error response — that raise is a controlled outcome, not a failed
    transaction, so it must not roll back the write that led to it. A raw
    HTTPException(...) constructed *without* first writing anything (e.g. a 404 for a
    deal that doesn't exist) has nothing to lose by this and behaves identically
    either way. Any other exception (a real bug, a DB error) still rolls back, exactly
    as `with conn.transaction()` would do on its own.
    """
    pool = get_pool()
    with pool.connection() as conn:
        http_exc: HTTPException | None = None
        with conn.transaction():
            if claims is not None:
                conn.execute(
                    "select set_config('request.jwt.claims', %s, true)",
                    (json.dumps(claims),),
                )
            try:
                yield conn
            except HTTPException as exc:
                http_exc = exc
        if http_exc is not None:
            raise http_exc
