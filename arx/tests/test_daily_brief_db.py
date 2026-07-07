"""Integration tests for the Daily Intelligence Brief (Section 40) against a live
Postgres + FastAPI app. Skipped automatically if no DATABASE_URL is reachable.
"""
import time
import uuid

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


def _mint_token(org_id: str, user_id: str, role: str) -> str:
    return jwt.encode(
        {"sub": user_id, "org_id": org_id, "role": role, "exp": int(time.time()) + 3600},
        settings.secret_key, algorithm="HS256",
    )


@pytest.fixture
def org_id():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    _org_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_BRIEF_ORG', 500000) returning org_id"
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
def client(org_id):
    from arx.api.main import app
    return TestClient(app)


def test_brief_includes_stalled_deal(client, org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    deal_id = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, momentum_score) "
        "values (%s, 'Stalled deal', 'acquisition', 'underwriting', 5) returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.close()

    token = _mint_token(org_id, str(uuid.uuid4()), "admin")
    resp = client.get("/api/v1/brief", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    stalled_ids = [d["deal_id"] for d in body["stalled_deal_alerts"]]
    assert str(deal_id) in stalled_ids


def test_brief_includes_blocked_task_and_recommends_action(client, org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    deal_id = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status) "
        "values (%s, 'Blocked deal', 'acquisition', 'due_diligence') returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.execute(
        "insert into deal_tasks (deal_id, org_id, title, status) values (%s, %s, 'Title review', 'blocked')",
        (deal_id, org_id),
    )
    conn.close()

    token = _mint_token(org_id, str(uuid.uuid4()), "admin")
    resp = client.get("/api/v1/brief", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    blocked_deal_ids = [t["deal_id"] for t in body["blocked_tasks"]]
    assert str(deal_id) in blocked_deal_ids
    recs = {r["deal_id"]: r["recommendation"] for r in body["recommended_next_actions"]}
    assert "blocked" in recs[str(deal_id)].lower()


def test_brief_dd_countdown_reports_days_in_due_diligence(client, org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    deal_id = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, days_in_current_status) "
        "values (%s, 'DD deal', 'acquisition', 'due_diligence', 5) returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.close()

    token = _mint_token(org_id, str(uuid.uuid4()), "admin")
    resp = client.get("/api/v1/brief", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    countdown = next(d for d in resp.json()["dd_countdowns"] if d["deal_id"] == str(deal_id))
    assert countdown["days_in_due_diligence"] == 5


def test_brief_analyst_only_sees_assigned_deals(client, org_id):
    analyst_id = str(uuid.uuid4())
    conn = psycopg.connect(settings.database_url, autocommit=True)
    assigned_deal = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, assigned_user_id, momentum_score) "
        "values (%s, 'My deal', 'acquisition', 'lead', %s, 5) returning deal_id",
        (org_id, analyst_id),
    ).fetchone()[0]
    other_deal = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, momentum_score) "
        "values (%s, 'Someone elses deal', 'acquisition', 'lead', 5) returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.close()

    token = _mint_token(org_id, analyst_id, "analyst")
    resp = client.get("/api/v1/brief", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    stalled_ids = [d["deal_id"] for d in resp.json()["stalled_deal_alerts"]]
    assert str(assigned_deal) in stalled_ids
    assert str(other_deal) not in stalled_ids


def test_brief_requires_admin_or_analyst_role(client, org_id):
    token = _mint_token(org_id, str(uuid.uuid4()), "viewer")
    resp = client.get("/api/v1/brief", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
