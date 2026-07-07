"""Integration tests for Section 59 Network Intelligence Layer against a live
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
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_NETWORK_ORG', 500000) returning org_id"
        ).fetchone()[0])
        yield _org_id
    finally:
        if _org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (_org_id,))
        conn.close()


def _closed_deal_with_a02(org_id, *, closed_days_ago=45, deal_type="acquisition", submarket="Tacoma"):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    deal_id = str(conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price, unit_count, submarket) "
        "values (%s, 'Contrib Deal', %s, 'closed', 5000000, 24, %s) returning deal_id",
        (org_id, deal_type, submarket),
    ).fetchone()[0])
    closed_at = f"now() - interval '{closed_days_ago} days'"
    conn.execute(
        f"insert into deal_status_history (deal_id, org_id, status, entered_at) values (%s, %s, 'closed', {closed_at})",
        (deal_id, org_id),
    )
    if deal_type == "acquisition":
        conn.execute(
            "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, "
            "input_payload, output_payload) values (%s, %s, 'a02', 1, true, '{}'::jsonb, %s::jsonb)",
            (deal_id, org_id, json.dumps({"purchase_price": 5_000_000, "cap_rate": 0.06})),
        )
    conn.close()
    return deal_id


def _opt_in(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute("update orgs set network_participation = true where org_id = %s", (org_id,))
    conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_contribution_rejected_without_org_opt_in(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _closed_deal_with_a02(org_id)
    resp = client.post(
        f"/api/v1/deals/{deal_id}/network-contribution",
        headers={"Authorization": f"Bearer {token}"}, json={"consent": True},
    )
    assert resp.status_code == 409
    assert "opted in" in resp.json()["detail"]


def test_contribution_rejected_without_user_consent(client_and_token, org_id):
    client, token = client_and_token
    _opt_in(org_id)
    deal_id = _closed_deal_with_a02(org_id)
    resp = client.post(
        f"/api/v1/deals/{deal_id}/network-contribution",
        headers={"Authorization": f"Bearer {token}"}, json={"consent": False},
    )
    assert resp.status_code == 409
    assert "consent" in resp.json()["detail"]


def test_contribution_rejected_before_30_day_window(client_and_token, org_id):
    client, token = client_and_token
    _opt_in(org_id)
    deal_id = _closed_deal_with_a02(org_id, closed_days_ago=10)
    resp = client.post(
        f"/api/v1/deals/{deal_id}/network-contribution",
        headers={"Authorization": f"Bearer {token}"}, json={"consent": True},
    )
    assert resp.status_code == 409
    assert "30" in resp.json()["detail"]


def test_contribution_rejected_for_development_deal(client_and_token, org_id):
    client, token = client_and_token
    _opt_in(org_id)
    deal_id = _closed_deal_with_a02(org_id, deal_type="development")
    resp = client.post(
        f"/api/v1/deals/{deal_id}/network-contribution",
        headers={"Authorization": f"Bearer {token}"}, json={"consent": True},
    )
    assert resp.status_code == 409
    assert "acquisition" in resp.json()["detail"]


def test_successful_contribution_persists_anonymized_row(client_and_token, org_id):
    client, token = client_and_token
    _opt_in(org_id)
    deal_id = _closed_deal_with_a02(org_id)
    resp = client.post(
        f"/api/v1/deals/{deal_id}/network-contribution",
        headers={"Authorization": f"Bearer {token}"}, json={"consent": True, "financing_type": "bank_loan"},
    )
    assert resp.status_code == 201, resp.text

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select submarket, close_cap_rate, price_per_unit, financing_type from network_contributions "
        "where contribution_id = %s", (resp.json()["contribution_id"],),
    ).fetchone()
    conn.close()
    assert row[0] == "Tacoma"
    assert float(row[1]) == pytest.approx(0.06)
    assert float(row[2]) == pytest.approx(5_000_000 / 24)
    assert row[3] == "bank_loan"


def test_network_status_counts_distinct_contributing_orgs(client_and_token, org_id):
    client, token = client_and_token
    _opt_in(org_id)
    deal_id = _closed_deal_with_a02(org_id)
    client.post(
        f"/api/v1/deals/{deal_id}/network-contribution",
        headers={"Authorization": f"Bearer {token}"}, json={"consent": True},
    )

    resp = client.get("/api/v1/network-intelligence/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["contributing_org_count"] >= 1
    assert resp.json()["tier"] == "below_threshold"  # 1 org is well under the 5-org threshold


def test_network_comps_aggregates_across_submarket(client_and_token, org_id):
    client, token = client_and_token
    _opt_in(org_id)
    deal_id = _closed_deal_with_a02(org_id, submarket="Puyallup")
    client.post(
        f"/api/v1/deals/{deal_id}/network-contribution",
        headers={"Authorization": f"Bearer {token}"}, json={"consent": True},
    )

    resp = client.get(
        "/api/v1/network-intelligence/comps?submarket=Puyallup", headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contribution_count"] >= 1
    assert body["avg_cap_rate"] == pytest.approx(0.06)


def test_patch_network_opt_in_requires_admin(client_and_token):
    client, token = client_and_token
    resp = client.patch(
        "/api/v1/org/network-opt-in",
        headers={"Authorization": f"Bearer {token}"}, json={"network_participation": True},
    )
    assert resp.status_code == 403
