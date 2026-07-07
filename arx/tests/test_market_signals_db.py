"""Integration tests for Section 62 Market Signal Processing against a live Postgres +
FastAPI app. Skipped automatically if no DATABASE_URL is reachable.
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
        _org_id = str(conn.execute(
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_MKT_SIGNAL_ORG', 500000) returning org_id"
        ).fetchone()[0])
        yield _org_id
    finally:
        if _org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (_org_id,))
        conn.close()


def _insert_deal(org_id, submarket, status="underwriting", property_address=None):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price, submarket) "
        "values (%s, %s, 'acquisition', %s, 5000000, %s) returning deal_id",
        (org_id, property_address or f"Test Deal {submarket}", status, submarket),
    ).fetchone()
    conn.close()
    return str(row[0])


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_low_significance_signal_does_not_route(client_and_token, org_id):
    client, token = client_and_token
    _insert_deal(org_id, "Tacoma")
    resp = client.post(
        "/api/v1/market-signals",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "signal_type": "cap_rate", "submarket": "Tacoma", "signal_value": 0.062,
            "prior_value": 0.060, "significance": "low",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["affected_deal_ids"] == []


def test_high_significance_signal_routes_to_affected_deals_and_notifies(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, "Tacoma")
    _insert_deal(org_id, "Seattle")  # different submarket, should not be affected

    resp = client.post(
        "/api/v1/market-signals",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "signal_type": "interest_rate", "submarket": "Tacoma", "signal_value": 0.075,
            "prior_value": 0.065, "significance": "high",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["affected_deal_ids"] == [deal_id]

    conn = psycopg.connect(settings.database_url, autocommit=True)
    signal_row = conn.execute(
        "select deal_impacts, change_pct from market_signals where signal_id = %s", (body["signal_id"],)
    ).fetchone()
    notif_count = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'market_signal_deal_impact'",
        (org_id,),
    ).fetchone()[0]
    conn.close()

    assert signal_row[0] == [deal_id]
    assert float(signal_row[1]) == pytest.approx((0.075 - 0.065) / 0.065)
    assert notif_count == 1


def test_high_significance_signal_does_not_affect_closed_or_dead_deals(client_and_token, org_id):
    client, token = client_and_token
    _insert_deal(org_id, "Tacoma", status="closed")

    resp = client.post(
        "/api/v1/market-signals",
        headers={"Authorization": f"Bearer {token}"},
        json={"signal_type": "cap_rate", "submarket": "Tacoma", "signal_value": 0.07, "significance": "high"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["affected_deal_ids"] == []


def test_list_market_signals_filters_by_submarket(client_and_token, org_id):
    client, token = client_and_token
    client.post(
        "/api/v1/market-signals", headers={"Authorization": f"Bearer {token}"},
        json={"signal_type": "cap_rate", "submarket": "Tacoma", "signal_value": 0.06},
    )
    client.post(
        "/api/v1/market-signals", headers={"Authorization": f"Bearer {token}"},
        json={"signal_type": "cap_rate", "submarket": "Seattle", "signal_value": 0.055},
    )
    resp = client.get("/api/v1/market-signals?submarket=Tacoma", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    signals = resp.json()
    assert len(signals) == 1
    assert signals[0]["submarket"] == "Tacoma"
