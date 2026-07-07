"""Integration tests for arx/db/queries/{snapshots,quality_log}.py against a real
Postgres instance. Skipped automatically if no DATABASE_URL is reachable (same
pattern as test_phase1_smoke.py).
"""
import json

import psycopg
import pytest

from arx.api.config import get_settings
from arx.db.queries.quality_log import record_agent_run, record_error
from arx.db.queries.snapshots import activate_snapshot, get_active_snapshot, write_snapshot

try:
    settings = get_settings()
    _conn = psycopg.connect(settings.database_url, connect_timeout=3)
    _conn.close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="No reachable DATABASE_URL configured")


@pytest.fixture
def test_org_and_deal():
    """Bootstraps directly against DATABASE_URL (bypasses RLS by design — this is
    fixture setup, not request-handling code; see arx/db/connection.py's docstring)."""
    conn = psycopg.connect(settings.database_url, autocommit=True)
    org_id = deal_id = None
    try:
        with conn.cursor() as cur:
            cur.execute("insert into orgs (org_name) values ('TEST_SNAPSHOT_ORG') returning org_id")
            org_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into deals (org_id, property_address, deal_type) values (%s, %s, 'acquisition') returning deal_id",
                (org_id, "1 Snapshot Test Way"),
            )
            deal_id = str(cur.fetchone()[0])
        yield org_id, deal_id
    finally:
        if org_id:
            # This cascades into deal_snapshots, which blocks ordinary deletes
            # (Section 13) — test teardown is exactly the kind of deliberate,
            # explicit purge that guard is designed to allow (see
            # arx/db/migrations/023_amend_snapshot_delete_guard.sql). SET LOCAL only
            # applies for the duration of one transaction, hence the explicit block —
            # this connection is autocommit, so each bare statement is its own
            # transaction and a SET LOCAL on a prior statement wouldn't carry over.
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (org_id,))
        conn.close()


@pytest.fixture
def app_conn(test_org_and_deal):
    """A connection using the RLS-bound app role, same one the running API uses —
    with request.jwt.claims set for the test org, exactly like arx/db/connection.py's
    db_session() does per-request in production. Without this, RLS correctly rejects
    every write (there's no authenticated org context), which is what a first version
    of this fixture ran into."""
    org_id, _ = test_org_and_deal
    conn = psycopg.connect(settings.app_database_url, autocommit=True)
    conn.execute(
        "select set_config('request.jwt.claims', %s, false)",
        (json.dumps({"org_id": org_id, "role": "analyst", "sub": "00000000-0000-0000-0000-000000000001"}),),
    )
    yield conn
    conn.close()


def test_write_activate_and_read_snapshot(test_org_and_deal, app_conn):
    org_id, deal_id = test_org_and_deal

    v1_id = write_snapshot(
        app_conn, deal_id=deal_id, org_id=org_id, agent_id="a02",
        input_payload={"purchase_price": 5_000_000}, output_payload={"noi": 300_000},
        confidence_score="high",
    )
    # Not active until explicitly activated (Section 13).
    assert get_active_snapshot(app_conn, deal_id=deal_id, agent_id="a02") is None

    activate_snapshot(app_conn, deal_id=deal_id, agent_id="a02", snapshot_id=v1_id)
    active = get_active_snapshot(app_conn, deal_id=deal_id, agent_id="a02")
    assert active is not None
    assert str(active["snapshot_id"]) == v1_id
    assert active["output_payload"] == {"noi": 300_000}

    # A re-run creates version 2, doesn't overwrite version 1, and activating it
    # deactivates version 1 (G-05: exactly one active per deal+agent).
    v2_id = write_snapshot(
        app_conn, deal_id=deal_id, org_id=org_id, agent_id="a02",
        input_payload={"purchase_price": 5_100_000}, output_payload={"noi": 305_000},
        confidence_score="high",
    )
    assert v2_id != v1_id
    activate_snapshot(app_conn, deal_id=deal_id, agent_id="a02", snapshot_id=v2_id)

    active = get_active_snapshot(app_conn, deal_id=deal_id, agent_id="a02")
    assert str(active["snapshot_id"]) == v2_id
    assert active["output_payload"] == {"noi": 305_000}

    # v1 still exists, just inactive — never deleted (Section 13).
    row = app_conn.execute(
        "select is_active from deal_snapshots where snapshot_id = %s", (v1_id,)
    ).fetchone()
    assert row[0] is False


def test_record_agent_run_and_error(test_org_and_deal, app_conn):
    org_id, deal_id = test_org_and_deal

    record_agent_run(
        app_conn, org_id=org_id, deal_id=deal_id, agent_id="a02", prompt_version="1.0.0",
        confidence_score="high", validation_passed=True, failed_checks=None, token_count=1234,
    )
    row = app_conn.execute(
        "select validation_passed, token_count from agent_quality_log where deal_id = %s", (deal_id,)
    ).fetchone()
    assert row == (True, 1234)

    error_id = record_error(
        app_conn, org_id=org_id, deal_id=deal_id, error_type="validation_failure",
        agent_id="a02", step="math_validation",
        input_payload={"noi": 300_000}, raw_output="{...}",
        failed_checks={"passed": False, "checks": [{"check_id": "MV1", "passed": False}]},
    )
    row = app_conn.execute(
        "select resolution_status, error_type from error_log where error_id = %s", (error_id,)
    ).fetchone()
    assert row == ("open", "validation_failure")
