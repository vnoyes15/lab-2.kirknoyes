"""Integration tests for the Portfolio Layer (Section 29) against a live Postgres +
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
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_PORTFOLIO_ORG', 500000) returning org_id"
            )
            _org_id = str(cur.fetchone()[0])
        yield _org_id
    finally:
        if _org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (_org_id,))
        conn.close()


def _insert_deal(org_id: str, **overrides) -> str:
    conn = psycopg.connect(settings.database_url, autocommit=True)
    fields = {
        "org_id": org_id, "property_address": overrides.pop("property_address", "123 Main St"),
        "deal_type": "acquisition", "status": "closed", "asking_price": 1_000_000,
        "is_acquired": True, "close_reason_code": None,
    }
    fields.update(overrides)
    if fields["status"] == "dead" and fields.get("close_reason_code") is None:
        fields["close_reason_code"] = "other"
    cols = ", ".join(fields)
    placeholders = ", ".join(f"%({k})s" for k in fields)
    row = conn.execute(
        f"insert into deals ({cols}) values ({placeholders}) returning deal_id", fields
    ).fetchone()
    conn.close()
    return str(row[0])


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_record_performance_requires_acquired_deal(client_and_token, org_id):
    client, token = client_and_token
    unowned_deal = _insert_deal(org_id, status="lead", is_acquired=False)

    resp = client.post(
        f"/api/v1/deals/{unowned_deal}/performance",
        headers={"Authorization": f"Bearer {token}"},
        json={"period": "2026-07-01", "actual_noi": 30000},
    )
    assert resp.status_code == 409


def test_record_and_list_performance(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id)

    resp = client.post(
        f"/api/v1/deals/{deal_id}/performance",
        headers={"Authorization": f"Bearer {token}"},
        json={"period": "2026-07-01", "actual_noi": 30000, "actual_gross_rent": 45000},
    )
    assert resp.status_code == 201, resp.text

    resp = client.get(f"/api/v1/deals/{deal_id}/performance", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert float(body[0]["actual_noi"]) == 30000


def test_portfolio_summary_aggregates_owned_assets(client_and_token, org_id):
    client, token = client_and_token
    deal1 = _insert_deal(org_id, property_address="Owned deal 1")
    deal2 = _insert_deal(org_id, property_address="Owned deal 2")
    _insert_deal(org_id, property_address="Unowned deal", status="lead", is_acquired=False)

    client.post(
        f"/api/v1/deals/{deal1}/performance", headers={"Authorization": f"Bearer {token}"},
        json={"period": "2026-07-01", "actual_noi": 10000},
    )
    client.post(
        f"/api/v1/deals/{deal2}/performance", headers={"Authorization": f"Bearer {token}"},
        json={"period": "2026-07-01", "actual_noi": 20000},
    )

    resp = client.get("/api/v1/portfolio", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["asset_count"] == 2
    assert body["total_latest_monthly_noi"] == 30000


def test_development_pipeline_includes_milestones_and_budget_variance(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(
        org_id, property_address="Dev deal", deal_type="development", status="construction",
        is_acquired=True,
    )
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into development_milestones (deal_id, org_id, milestone_type, projected_date, status) "
        "values (%s, %s, 'stabilization', '2027-01-01', 'projected')",
        (deal_id, org_id),
    )
    conn.execute(
        "insert into construction_budget (deal_id, org_id, line_item, budget_amount, variance_amount) "
        "values (%s, %s, 'Framing', 500000, 25000)",
        (deal_id, org_id),
    )
    conn.close()

    resp = client.get("/api/v1/portfolio/development", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    dev_deal = next(d for d in body if d["deal_id"] == deal_id)
    assert dev_deal["construction_budget_variance"] == 25000
    assert dev_deal["projected_stabilization_date"] == "2027-01-01"
    assert len(dev_deal["milestones"]) == 1
