"""Integration tests for Output Accuracy Flagging (Section 35) against a live
Postgres + FastAPI app. Skipped automatically if no DATABASE_URL is reachable.
"""
import time

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from arx.api.config import get_settings

try:
    settings = get_settings()
    _conn = psycopg.connect(settings.database_url, connect_timeout=3)
    _conn.close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="No reachable DATABASE_URL configured")


def _mint_token(org_id: str, role: str = "analyst") -> str:
    return jwt.encode(
        {"sub": "00000000-0000-0000-0000-0000000000aa", "org_id": org_id, "role": role, "exp": int(time.time()) + 3600},
        settings.secret_key, algorithm="HS256",
    )


@pytest.fixture
def org_id():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    _org_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_ACCURACY_ORG', 500000) returning org_id"
            )
            _org_id = str(cur.fetchone()[0])
        yield _org_id
    finally:
        if _org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (_org_id,))
        conn.close()


@pytest.fixture
def deal_id(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        row = conn.execute(
            "insert into deals (org_id, property_address, deal_type, status, asking_price) "
            "values (%s, '123 Main St', 'acquisition', 'underwriting', 1000000) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


def _insert_snapshot(org_id: str, deal_id: str, agent_id: str = "a02") -> str:
    conn = psycopg.connect(settings.database_url, autocommit=True)
    next_version = conn.execute(
        "select coalesce(max(version_number), 0) + 1 from deal_snapshots where deal_id = %s and agent_id = %s",
        (deal_id, agent_id),
    ).fetchone()[0]
    row = conn.execute(
        "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, input_payload, output_payload) "
        "values (%s, %s, %s, %s, '{}'::jsonb, '{}'::jsonb) returning snapshot_id",
        (deal_id, org_id, agent_id, next_version),
    ).fetchone()
    conn.close()
    return str(row[0])


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_flag_accuracy_persists(client_and_token, deal_id, org_id):
    client, token = client_and_token
    snapshot_id = _insert_snapshot(org_id, deal_id)

    resp = client.patch(
        f"/api/v1/deals/{deal_id}/agents/a02/snapshots/{snapshot_id}/accuracy",
        headers={"Authorization": f"Bearer {token}"},
        json={"accuracy_flag": "partial", "accuracy_note": "Vacancy assumption looked optimistic."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accuracy_flag"] == "partial"

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select accuracy_flag, accuracy_note from deal_snapshots where snapshot_id = %s", (snapshot_id,)
    ).fetchone()
    conn.close()
    assert row[0] == "partial"
    assert row[1] == "Vacancy assumption looked optimistic."


def test_flag_unknown_snapshot_404s(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.patch(
        f"/api/v1/deals/{deal_id}/agents/a02/snapshots/00000000-0000-0000-0000-000000000000/accuracy",
        headers={"Authorization": f"Bearer {token}"},
        json={"accuracy_flag": "accurate"},
    )
    assert resp.status_code == 404


def test_three_inaccurate_flags_triggers_admin_notification(client_and_token, deal_id, org_id):
    client, token = client_and_token
    for _ in range(3):
        snapshot_id = _insert_snapshot(org_id, deal_id)
        resp = client.patch(
            f"/api/v1/deals/{deal_id}/agents/a02/snapshots/{snapshot_id}/accuracy",
            headers={"Authorization": f"Bearer {token}"},
            json={"accuracy_flag": "inaccurate", "accuracy_note": "NOI construction did not match rent roll."},
        )
        assert resp.status_code == 200, resp.text

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'accuracy_flag_threshold'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 1


def test_two_inaccurate_flags_does_not_trigger_notification(client_and_token, deal_id, org_id):
    client, token = client_and_token
    for _ in range(2):
        snapshot_id = _insert_snapshot(org_id, deal_id)
        client.patch(
            f"/api/v1/deals/{deal_id}/agents/a02/snapshots/{snapshot_id}/accuracy",
            headers={"Authorization": f"Bearer {token}"},
            json={"accuracy_flag": "inaccurate", "accuracy_note": "Cap rate seemed off given the comps."},
        )

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'accuracy_flag_threshold'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 0


def test_lp_role_accepted_by_jwt_but_403_on_admin_analyst_endpoints(client_and_token, deal_id, org_id):
    client, _ = client_and_token
    lp_token = _mint_token(org_id, role="lp")
    snapshot_id = _insert_snapshot(org_id, deal_id)

    resp = client.patch(
        f"/api/v1/deals/{deal_id}/agents/a02/snapshots/{snapshot_id}/accuracy",
        headers={"Authorization": f"Bearer {lp_token}"},
        json={"accuracy_flag": "accurate"},
    )
    assert resp.status_code == 403
