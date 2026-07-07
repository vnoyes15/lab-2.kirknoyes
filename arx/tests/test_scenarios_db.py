"""Integration tests for the Deal Scenario Modeling API (Section 63) against a live
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
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_SCENARIO_ORG', 500000) returning org_id"
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
            "values (%s, '123 Main St', 'acquisition', 'underwriting', 5000000) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


def _insert_active_a02_snapshot(org_id: str, deal_id: str) -> None:
    output = {
        "gross_rent": 500_000, "vacancy_rate": 0.07, "vacancy_amount": 35_000,
        "operating_expenses": {"management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
                                "insurance": 25_000, "taxes": 40_000, "other": 10_000},
        "purchase_price": 5_000_000, "cap_rate": 0.06, "loan_amount": 3_750_000, "ltv": 0.75,
        "interest_rate": 0.065, "amortization_years": 30, "annual_debt_service": 284_355.83,
        "noi": 300_000, "dscr": 1.055, "dscr_hard_fail": False, "dscr_warning": True, "cash_on_cash": 0.012,
        "sensitivity_table": {"base": {"cap_rate": 0.06, "dscr": 1.055, "coc": 0.012}},
        "load_bearing_assumptions": [{"assumption": "x", "why_it_matters": "y"}] * 3,
        "assumption_sources": {"gross_rent": "user_provided"}, "confidence_score": "high",
    }
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, input_payload, output_payload) "
        "values (%s, %s, 'a02', 1, true, '{}'::jsonb, %s::jsonb)",
        (deal_id, org_id, json.dumps(output)),
    )
    conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_scenario_without_active_baseline_409s(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/scenarios",
        headers={"Authorization": f"Bearer {token}"},
        json={"scenario_name": "Bear case", "track": "acquisition", "rent_change_pct": -0.08},
    )
    assert resp.status_code == 409


def test_scenario_creates_and_persists(client_and_token, deal_id, org_id):
    client, token = client_and_token
    _insert_active_a02_snapshot(org_id, deal_id)

    resp = client.post(
        f"/api/v1/deals/{deal_id}/scenarios",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "scenario_name": "Bear case", "track": "acquisition",
            "rent_change_pct": -0.08, "expense_change_pct": 0.05,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["scenario_name"] == "Bear case"
    assert body["output"]["noi"] < 300_000

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select scenario_name from scenario_models where deal_id = %s", (deal_id,)
    ).fetchone()
    conn.close()
    assert row[0] == "Bear case"


def test_list_scenarios_returns_multiple_named_scenarios_side_by_side(client_and_token, deal_id, org_id):
    client, token = client_and_token
    _insert_active_a02_snapshot(org_id, deal_id)

    for name, rent_change in [("Base case", 0.0), ("Bear case", -0.08), ("Bull case", 0.05)]:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/scenarios",
            headers={"Authorization": f"Bearer {token}"},
            json={"scenario_name": name, "track": "acquisition", "rent_change_pct": rent_change},
        )
        assert resp.status_code == 201, resp.text

    resp = client.get(f"/api/v1/deals/{deal_id}/scenarios", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    names = [s["scenario_name"] for s in resp.json()]
    assert names == ["Base case", "Bear case", "Bull case"]
