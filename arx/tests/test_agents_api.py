"""Integration tests for arx/api/agents.py against a live Postgres + FastAPI app.
Skipped automatically if no DATABASE_URL is reachable (same pattern as
test_phase1_smoke.py). The real Anthropic client is never constructed — every test
overrides model_client_dependency with a FakeModelClient.
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
        {"sub": "00000000-0000-0000-0000-0000000000aa", "org_id": org_id, "role": role,
         "exp": int(time.time()) + 3600},
        settings.secret_key, algorithm="HS256",
    )


@pytest.fixture
def org_with_config():
    """Bootstraps an org with an active acquisition uw_config (bypasses RLS by
    design — see arx/db/connection.py's docstring on why fixture/script code may)."""
    conn = psycopg.connect(settings.database_url, autocommit=True)
    org_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_AGENTS_API_ORG', 500000) returning org_id"
            )
            org_id = str(cur.fetchone()[0])
            cur.execute(
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
            "insert into deals (org_id, property_address, deal_type, asking_price, unit_count) "
            "values (%s, %s, 'acquisition', %s, 24) returning deal_id",
            (org_with_config, "123 Main St, Tacoma WA", PURCHASE_PRICE),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


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


def test_invoke_a01_creates_inactive_snapshot(client_and_token, deal_id):
    client, token = client_and_token
    fake = FakeModelClient({
        "deal_id": deal_id, "deal_type_detected": "acquisition", "go_no_go": "go",
        "preliminary_cap_rate": 0.06, "preliminary_roc": None, "in_target_range": True,
        "missing_fields": [], "rationale": "Within target cap rate range for this submarket and asset type.",
        "routing_recommendation": "route_to_a02", "confidence_score": "medium",
        "document_extraction_required": False,
    })
    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a01",
            headers={"Authorization": f"Bearer {token}"}, json={},
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["output"]["go_no_go"] == "go"
    assert body["snapshot_id"]


def test_invoke_a02_then_activate_then_a07(client_and_token, deal_id):
    client, token = client_and_token
    headers = {"Authorization": f"Bearer {token}"}

    from arx.api.main import app

    app.dependency_overrides[model_client_dependency] = lambda: FakeModelClient(_a02_response())
    try:
        resp = client.post(f"/api/v1/deals/{deal_id}/agents/a02", headers=headers, json={})
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)
    assert resp.status_code == 200, resp.text
    a02_body = resp.json()
    assert a02_body["validation"]["passed"] is True
    a02_snapshot_id = a02_body["snapshot_id"]

    # A-07 before activation: no active a02 snapshot yet -> 409 (Section 13).
    memo_response = {
        "memo_track": "acquisition",
        "sections": {
            "executive_summary": "x", "property_overview": "x", "market_context": "x",
            "investment_thesis": "x", "financial_summary": "x", "risk_factors": "x" * 210,
            "deal_structure": "x", "next_steps": "x",
        },
        "financial_summary_metrics": {"cap_rate": NOI / PURCHASE_PRICE, "noi": NOI, "dscr": DSCR, "cash_on_cash": COC},
        "confidence_disclosure": None,
        "audience_version": "internal",
    }
    app.dependency_overrides[model_client_dependency] = lambda: FakeModelClient(memo_response)
    try:
        resp_before = client.post(f"/api/v1/deals/{deal_id}/agents/a07", headers=headers, json={})
        assert resp_before.status_code == 409

        activate_resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a02/snapshots/{a02_snapshot_id}/activate", headers=headers,
        )
        assert activate_resp.status_code == 200

        resp_after = client.post(f"/api/v1/deals/{deal_id}/agents/a07", headers=headers, json={})
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)

    assert resp_after.status_code == 200, resp_after.text
    assert resp_after.json()["output"]["memo_track"] == "acquisition"


def test_invoke_a02_validation_failure_returns_422_and_logs_error(client_and_token, deal_id):
    client, token = client_and_token
    bad_response = _a02_response(cap_rate=0.5)  # inconsistent with noi/price -> MV1 fails

    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: FakeModelClient(bad_response)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a02", headers={"Authorization": f"Bearer {token}"}, json={},
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error_id"]
    failed_ids = {c["check_id"] for c in detail["failed_checks"]["checks"] if not c["passed"]}
    assert "MV1" in failed_ids


def test_viewer_role_forbidden_from_agent_endpoints(client_and_token, deal_id, org_with_config):
    client, _ = client_and_token
    viewer_token = _mint_token(org_with_config, role="viewer")
    resp = client.post(
        f"/api/v1/deals/{deal_id}/agents/a01",
        headers={"Authorization": f"Bearer {viewer_token}"}, json={},
    )
    assert resp.status_code == 403


def test_upload_rent_roll_document_no_model_call(client_and_token, deal_id):
    client, token = client_and_token
    csv_bytes = (
        b"unit_id,lease_start,lease_end,contracted_rent,payment_status\n"
        b"101,2025-01-01,2026-01-01,1500,current\n"
        b"102,2025-01-01,2026-01-01,0,vacant\n"
    )
    fake = FakeModelClient({})  # must never be called for a rent_roll upload

    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            data={"doc_type": "rent_roll"},
            files={"file": ("rent_roll.csv", csv_bytes, "text/csv")},
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["output"]["extracted_fields"]["gross_rent"]["value"] == 1500
    assert len(fake.calls) == 0


def test_budget_exhausted_blocks_agent_call(client_and_token, deal_id, org_with_config):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute("update orgs set token_used_this_month = token_budget_monthly where org_id = %s", (org_with_config,))
    conn.close()

    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/agents/a01", headers={"Authorization": f"Bearer {token}"}, json={},
    )
    assert resp.status_code == 429
