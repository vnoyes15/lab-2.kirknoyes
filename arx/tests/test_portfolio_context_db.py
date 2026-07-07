"""Integration tests for Section 69 Portfolio Context wired into the A-02/A-11
endpoints, against a live Postgres + FastAPI app. Skipped automatically if no
DATABASE_URL is reachable.
"""
import json
import time

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from arx.agents.loan_math import compute_annual_debt_service
from arx.agents.model_client import model_client_dependency
from arx.api.config import get_settings
from arx.tests.fakes import FakeModelClient

try:
    settings = get_settings()
    _conn = psycopg.connect(settings.database_url, connect_timeout=3)
    _conn.close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="No reachable DATABASE_URL configured")

PURCHASE_PRICE = 5_000_000
LOAN_AMOUNT = 3_750_000
LTV, INTEREST_RATE, AMORT_YEARS = 0.75, 0.065, 30
NOI = 300_000
ANNUAL_DEBT_SERVICE = compute_annual_debt_service(LOAN_AMOUNT, INTEREST_RATE, AMORT_YEARS)
DSCR = NOI / ANNUAL_DEBT_SERVICE
COC = (NOI - ANNUAL_DEBT_SERVICE) / (PURCHASE_PRICE * (1 - LTV))


def _mint_token(org_id: str, role: str = "analyst") -> str:
    return jwt.encode(
        {"sub": "00000000-0000-0000-0000-0000000000aa", "org_id": org_id, "role": role, "exp": int(time.time()) + 3600},
        settings.secret_key, algorithm="HS256",
    )


@pytest.fixture
def org_with_config():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    org_id = None
    try:
        org_id = str(conn.execute(
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_PORT_CTX_ORG', 500000) returning org_id"
        ).fetchone()[0])
        conn.execute(
            "insert into uw_config (org_id, track, version, is_active, config) values (%s, 'acquisition', 1, true, %s)",
            (org_id, json.dumps({
                "vacancy": 0.07, "property_management": 0.08, "maintenance": 0.05, "capex_reserves": 0.05,
                "insurance_pct_of_price": 0.005, "ltv": LTV, "interest_rate": INTEREST_RATE,
                "amortization_years": AMORT_YEARS, "target_cap_rate_range": [0.055, 0.065],
            })),
        )
        yield org_id
    finally:
        if org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (org_id,))
        conn.close()


@pytest.fixture
def deal_id(org_with_config):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        row = conn.execute(
            "insert into deals (org_id, property_address, deal_type, asking_price, unit_count, submarket) "
            "values (%s, %s, 'acquisition', %s, 24, 'Seattle') returning deal_id",
            (org_with_config, "123 Main St, Seattle WA", PURCHASE_PRICE),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


def _insert_owned_asset(org_id: str, *, submarket: str, value: float, loan_amount: float, dscr: float):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    deal_row = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price, is_acquired, submarket) "
        "values (%s, 'Owned Asset', 'acquisition', 'closed', %s, true, %s) returning deal_id",
        (org_id, value, submarket),
    ).fetchone()
    deal_id = str(deal_row[0])
    debt_service = compute_annual_debt_service(loan_amount, INTEREST_RATE, AMORT_YEARS)
    payload = {
        "purchase_price": value, "loan_amount": loan_amount, "ltv": loan_amount / value,
        "dscr": dscr, "annual_debt_service": debt_service,
    }
    conn.execute(
        "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, "
        "input_payload, output_payload) values (%s, %s, 'a02', 1, true, '{}'::jsonb, %s::jsonb)",
        (deal_id, org_id, json.dumps(payload)),
    )
    conn.close()
    return deal_id


@pytest.fixture
def client_and_token(org_with_config):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_with_config)


def _a02_response(**overrides):
    scenario = lambda cap_rate: {"cap_rate": cap_rate, "dscr": DSCR, "coc": COC}
    base = {
        "gross_rent": 500_000, "vacancy_rate": 0.07, "vacancy_amount": 35_000,
        "operating_expenses": {"management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
                                "insurance": 25_000, "taxes": 40_000, "other": 10_000},
        "noi": NOI, "cap_rate": NOI / PURCHASE_PRICE, "dscr": DSCR, "cash_on_cash": COC,
        "sensitivity_table": {
            "rent_-10pct": scenario(0.052), "rent_-5pct": scenario(0.056), "base": scenario(0.06),
            "rent_+5pct": scenario(0.064), "rent_+10pct": scenario(0.068),
        },
        "load_bearing_assumptions": [
            {"assumption": "vacancy", "why_it_matters": "x"},
            {"assumption": "exit cap", "why_it_matters": "x"},
            {"assumption": "interest rate", "why_it_matters": "x"},
        ],
        "assumption_sources": {"gross_rent": "user_provided"},
        "confidence_score": "high",
        "no_comp_disclaimer": "No comps available.",
    }
    base.update(overrides)
    return base


def test_a02_response_includes_portfolio_context_with_no_owned_assets(client_and_token, deal_id):
    client, token = client_and_token
    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: FakeModelClient(_a02_response())
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a02",
            headers={"Authorization": f"Bearer {token}"}, json={},
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)
    assert resp.status_code == 200, resp.text
    context = resp.json()["portfolio_context"]
    assert context["current_weighted_average_dscr"] is None  # nothing owned yet
    assert context["geographic_concentration_before"] == 0.0
    assert context["geographic_concentration_after"] == 1.0  # this deal would be the whole portfolio


def test_a02_response_shows_diversification_reduces_concentration(client_and_token, deal_id, org_with_config):
    client, token = client_and_token
    _insert_owned_asset(org_with_config, submarket="Tacoma", value=9_000_000, loan_amount=6_750_000, dscr=1.3)

    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: FakeModelClient(_a02_response())
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a02",
            headers={"Authorization": f"Bearer {token}"}, json={},
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)
    assert resp.status_code == 200, resp.text
    context = resp.json()["portfolio_context"]

    assert context["geographic_concentration_submarket"] == "Seattle"
    assert context["geographic_concentration_before"] == 0.0
    assert context["current_weighted_average_dscr"] == pytest.approx(1.3)
    assert context["post_acquisition_weighted_average_dscr"] != pytest.approx(1.3)
    assert context["equity_deployment_impact"] == pytest.approx(PURCHASE_PRICE * (1 - LTV))
