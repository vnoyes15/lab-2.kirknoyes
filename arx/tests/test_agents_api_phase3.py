"""Integration tests for the Phase 3 API endpoints (A-03, A-04, A-05, A-12, A-13)
against a live Postgres + FastAPI app. Skipped automatically if no DATABASE_URL is
reachable. As in test_agents_api.py, the real Anthropic client is never constructed —
every test overrides model_client_dependency with a FakeModelClient.
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
LOAN_AMOUNT, LTV, INTEREST_RATE, AMORT_YEARS = 3_750_000, 0.75, 0.065, 30
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
def org_id():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    _org_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_PHASE3_ORG', 500000) returning org_id"
            )
            _org_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into org_jurisdictions (org_id, state_code, rent_control_active, rent_control_cap_formula, "
                "attorney_review_required) values (%s, 'WA', true, '7%% + CPI, or 10%%, whichever is lower', true)",
                (_org_id,),
            )
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
            "insert into deals (org_id, property_address, deal_type, asking_price, unit_count) "
            "values (%s, %s, 'acquisition', %s, 24) returning deal_id",
            (org_id, "123 Main St, Tacoma WA", PURCHASE_PRICE),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def contact_id(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        row = conn.execute(
            "insert into contacts (org_id, name, contact_category) values (%s, 'J. Smith', 'seller') returning contact_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def _override_model(fake):
    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    return app


def _clear_override():
    from arx.api.main import app
    app.dependency_overrides.pop(model_client_dependency, None)


# --------------------------------------------------------------------------- A-03 ---

def test_invoke_a03_logs_seller_profile_access(client_and_token, deal_id, contact_id, org_id):
    client, token = client_and_token
    fake = FakeModelClient({
        "seller_archetype": "distressed", "distress_indicators": ["tax delinquency"],
        "motivated_seller_score": 75,
        "outreach_approach": "Approach directly and briefly, emphasizing a fast as-is close given apparent "
                             "tax pressure on the owner.",
        "topics_to_avoid": ["Do not mention the tax lien directly."],
        "confidence_score": "medium",
    })
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a03",
            headers={"Authorization": f"Bearer {token}"},
            json={"contact_id": contact_id, "owner_name": "J. Smith"},
        )
    finally:
        _clear_override()

    assert resp.status_code == 200, resp.text
    assert resp.json()["output"]["seller_archetype"] == "distressed"

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from seller_profile_access_log where contact_id = %s", (contact_id,)
    ).fetchone()
    conn.close()
    assert row[0] == 1


def test_invoke_a03_unknown_contact_404s(client_and_token, deal_id):
    client, token = client_and_token
    fake = FakeModelClient({})
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a03",
            headers={"Authorization": f"Bearer {token}"},
            json={"contact_id": "00000000-0000-0000-0000-000000000000"},
        )
    finally:
        _clear_override()
    assert resp.status_code == 404


# ------------------------------------------------------------------ A-04 / A-12 (need active a02) ---

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
        "assumption_sources": {"gross_rent": "user_provided"}, "confidence_score": "high",
        "no_comp_disclaimer": "No comps available.",
    }
    base.update(overrides)
    return base


@pytest.fixture
def deal_with_active_a02(client_and_token, deal_id, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into uw_config (org_id, track, version, is_active, config) values (%s, 'acquisition', 1, true, %s)",
        (org_id, json.dumps({
            "vacancy": 0.07, "property_management": 0.08, "maintenance": 0.05, "capex_reserves": 0.05,
            "insurance_pct_of_price": 0.005, "ltv": LTV, "interest_rate": INTEREST_RATE,
            "amortization_years": AMORT_YEARS, "target_cap_rate_range": [0.055, 0.065],
        })),
    )
    conn.close()

    _override_model(FakeModelClient(_a02_response()))
    try:
        resp = client.post(f"/api/v1/deals/{deal_id}/agents/a02", headers={"Authorization": f"Bearer {token}"}, json={})
        assert resp.status_code == 200, resp.text
        a02_snapshot_id = resp.json()["snapshot_id"]
        activate_resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a02/snapshots/{a02_snapshot_id}/activate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert activate_resp.status_code == 200
    finally:
        _clear_override()
    return deal_id


def test_invoke_a04_without_active_a02_409s(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/agents/a04",
        headers={"Authorization": f"Bearer {token}"}, json={"seller_profile": {"seller_archetype": "distressed"}},
    )
    assert resp.status_code == 409


def test_invoke_a04_with_active_a02_succeeds(client_and_token, deal_with_active_a02):
    client, token = client_and_token
    strategy = lambda price: {
        "purchase_price": price, "financing_structure": "Standard bank financing.",
        "seller_rationale": "Seller is distressed and motivated by tax delinquency, likely to accept a fast, "
                             "as-is close below asking.",
        "zoniq_returns": {"cap_rate": NOI / price, "dscr": DSCR, "coc": COC},
        "key_risks": ["Rent roll unverified.", "Comps are dated."],
    }
    fake = FakeModelClient({
        "strategies": [strategy(4_700_000), strategy(4_900_000), strategy(5_000_000)],
        "feasibility_contingency_days": None,
    })
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_with_active_a02}/agents/a04",
            headers={"Authorization": f"Bearer {token}"},
            json={"seller_profile": {"seller_archetype": "distressed", "motivated_seller_score": 75}},
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["output"]["strategies"]) == 3


def test_invoke_a12_with_active_a02_succeeds(client_and_token, deal_with_active_a02):
    client, token = client_and_token
    fake = FakeModelClient({
        "counter_analysis": "The seller's counter is a modest $100,000 above our offer, suggesting they are "
                             "anchored near asking but open to negotiation.",
        "deal_impact": {"cap_rate_delta": -0.001, "dscr_delta": -0.01, "coc_delta": -0.001},
        "response_options": [
            {"label": "hold_firm", "description": "Hold at original offer.", "return_impact": {"cap_rate": 0.06}, "recommended": False},
            {"label": "partial_concession", "description": "Meet in the middle.", "return_impact": {"cap_rate": 0.059}, "recommended": True},
            {"label": "accept_counter", "description": "Accept as proposed.", "return_impact": {"cap_rate": 0.058}, "recommended": False},
        ],
        "recommendation_rationale": "Given the seller's apparent flexibility and a comparable deal that closed "
                                     "near the midpoint, a partial concession keeps returns within threshold while "
                                     "likely securing the deal without further delay or risk of losing it.",
        "below_threshold_flag": False,
    })
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_with_active_a02}/agents/a12",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "original_offer_strategy": {"purchase_price": 4_900_000},
                "seller_counter_terms": {"purchase_price": 5_000_000},
            },
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text
    assert resp.json()["output"]["below_threshold_flag"] is False


# --------------------------------------------------------------------------- A-05 ---

def test_invoke_a05_missing_jurisdiction_409s(client_and_token, deal_id):
    client, token = client_and_token
    fake = FakeModelClient({})
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a05",
            headers={"Authorization": f"Bearer {token}"},
            json={"state_code": "TX", "selected_offer_strategy": {"purchase_price": 4_900_000}},
        )
    finally:
        _clear_override()
    assert resp.status_code == 409


def test_invoke_a05_wa_success(client_and_token, deal_id):
    client, token = client_and_token
    fake = FakeModelClient({
        "loi_text": "x" * 520,
        "attorney_review_warning": "Buyer's attorney must review this LOI before execution. Unconditional.",
        "escrow_reference_present": True,
        "jurisdiction_flags": ["wa_rent_control_rcw59_18"],
    })
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a05",
            headers={"Authorization": f"Bearer {token}"},
            json={"state_code": "WA", "selected_offer_strategy": {"purchase_price": 4_900_000}},
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text
    assert resp.json()["output"]["escrow_reference_present"] is True


def test_invoke_a05_escrow_false_returns_422(client_and_token, deal_id):
    client, token = client_and_token
    fake = FakeModelClient({
        "loi_text": "x" * 520,
        "attorney_review_warning": "Buyer's attorney must review this LOI before execution.",
        "escrow_reference_present": False,
        "jurisdiction_flags": ["wa_rent_control_rcw59_18"],
    })
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a05",
            headers={"Authorization": f"Bearer {token}"},
            json={"state_code": "WA", "selected_offer_strategy": {"purchase_price": 4_900_000}},
        )
    finally:
        _clear_override()
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_id"]


# --------------------------------------------------------------------------- A-13 ---

def test_invoke_a13_with_no_lp_profiles_and_zero_closed_deals(client_and_token, deal_id):
    client, token = client_and_token
    fake = FakeModelClient({
        "investor_matches": [],
        "capital_structure_recommendation": "Raise $1.5M in LP equity via a simple LP/GP structure with an 8% "
                                             "preferred return, appropriate for this deal's size and risk profile "
                                             "given no LPs are currently on file to match against.",
        "track_record_summary": {"deals_closed": 0, "total_equity_deployed": 0.0,
                                  "avg_return_vs_projection": None, "strongest_precedent": None},
        "no_track_record_disclosure": "ZONIQ has not yet closed a deal on Arx; this raise is supported by "
                                       "underwriting rigor rather than historical returns.",
    })
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a13",
            headers={"Authorization": f"Bearer {token}"}, json={"equity_needed": 1_500_000},
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text
    assert resp.json()["output"]["track_record_summary"]["deals_closed"] == 0
    assert resp.json()["output"]["no_track_record_disclosure"] is not None
