"""Integration tests for Section 46 Refinance & Disposition Engine against a live
Postgres + FastAPI app. Skipped automatically if no DATABASE_URL is reachable.
"""
import json
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
        _org_id = str(conn.execute(
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_REFI_ORG', 500000) returning org_id"
        ).fetchone()[0])
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
            "insert into deals (org_id, property_address, deal_type, status, asking_price, is_acquired) "
            "values (%s, '123 Main St', 'acquisition', 'closed', 5000000, true) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


def _activate_a02_snapshot(org_id: str, deal_id: str, **overrides):
    fields = {
        "purchase_price": 5_000_000, "loan_amount": 3_750_000, "ltv": 0.75,
        "interest_rate": 0.065, "amortization_years": 30, "annual_debt_service": 284_262.65,
        "noi": 300_000, "cap_rate": 0.06,
    }
    fields.update(overrides)
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, "
        "input_payload, output_payload) values (%s, %s, 'a02', 1, true, '{}'::jsonb, %s::jsonb)",
        (deal_id, org_id, json.dumps(fields)),
    )
    conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_refi_analysis_requires_active_a02_snapshot(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/refi-analysis",
        headers={"Authorization": f"Bearer {token}"}, json={"proposed_interest_rate": 0.05},
    )
    assert resp.status_code == 409


def test_refi_analysis_unknown_deal_404s(client_and_token):
    client, token = client_and_token
    resp = client.post(
        "/api/v1/deals/00000000-0000-0000-0000-000000000000/refi-analysis",
        headers={"Authorization": f"Bearer {token}"}, json={"proposed_interest_rate": 0.05},
    )
    assert resp.status_code == 404


def test_refi_opportunity_triggers_notification(client_and_token, deal_id, org_id):
    client, token = client_and_token
    _activate_a02_snapshot(org_id, deal_id)

    resp = client.post(
        f"/api/v1/deals/{deal_id}/refi-analysis",
        headers={"Authorization": f"Bearer {token}"}, json={"proposed_interest_rate": 0.05},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["triggers_refi_opportunity"] is True
    assert body["cash_on_cash_improvement"] > 0

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'refi_opportunity'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 1


def test_refi_no_opportunity_no_notification(client_and_token, deal_id, org_id):
    client, token = client_and_token
    _activate_a02_snapshot(org_id, deal_id)

    resp = client.post(
        f"/api/v1/deals/{deal_id}/refi-analysis",
        headers={"Authorization": f"Bearer {token}"}, json={"proposed_interest_rate": 0.07},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["triggers_refi_opportunity"] is False

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'refi_opportunity'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 0


def test_disposition_opportunity_triggers_notification_and_1031_windows(client_and_token, deal_id, org_id):
    client, token = client_and_token
    _activate_a02_snapshot(org_id, deal_id, cap_rate=0.06)

    resp = client.post(
        f"/api/v1/deals/{deal_id}/disposition-analysis",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_market_cap_rate": 0.045, "disposition_date": "2026-07-01"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["triggers_disposition_opportunity"] is True
    assert body["section_1031_windows"]["identification_deadline"] == "2026-08-15"
    assert body["section_1031_windows"]["close_deadline"] == "2026-12-28"

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'disposition_opportunity'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 1
