"""Gate G-01 — Section 14: "Three real ZONIQ acquisition deals + one land deal pass
through all applicable agents without error or re-entry."

No real ZONIQ production data exists in this environment — same documented gap as
G-08 (arx/tests/test_gate_g08_document_intelligence.py), which already established the
precedent of a synthetic-but-realistic stand-in rather than skipping the gate
entirely. This test runs 3 distinct acquisition deals through intake -> A-01 -> A-02 ->
activate -> A-07 -> activate, and 1 land deal through intake -> A-01 -> A-10 -> A-11 ->
activate, end-to-end against the live API + live Postgres, asserting every step
succeeds on its first attempt ("without error or re-entry" — no step needs a retry or
a corrected resubmission to get a 2xx).
"""
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
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_G01_ORG', 500000) returning org_id"
        ).fetchone()[0])
        conn.execute(
            "insert into uw_config (org_id, track, version, is_active, config) values (%s, 'acquisition', 1, true, %s)",
            (_org_id, '{"vacancy": 0.07, "ltv": 0.75, "interest_rate": 0.065, "amortization_years": 30, '
                       '"target_cap_rate_range": [0.055, 0.065]}'),
        )
        conn.execute(
            "insert into uw_config (org_id, track, version, is_active, config) values (%s, 'development', 1, true, %s)",
            (_org_id, '{"soft_costs_pct_of_hard_min": 0.15, "soft_costs_pct_of_hard_max": 0.20, '
                       '"target_roc_range": [0.15, 0.20]}'),
        )
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


def _run_agent(client, token, deal_id, agent_id, payload, fake, expect_status=200):
    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"}, json=payload,
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)
    assert resp.status_code == expect_status, f"{agent_id}: {resp.status_code}: {resp.text}"
    return resp.json()


def _activate(client, token, deal_id, agent_id, snapshot_id):
    resp = client.post(
        f"/api/v1/deals/{deal_id}/agents/{agent_id}/snapshots/{snapshot_id}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


ACQUISITION_SCENARIOS = [
    {"address": "1 ZONIQ Test Ave, Tacoma WA", "purchase_price": 5_000_000, "gross_rent": 500_000, "units": 24},
    {"address": "2 ZONIQ Test Ave, Kent WA", "purchase_price": 2_200_000, "gross_rent": 240_000, "units": 12},
    {"address": "3 ZONIQ Test Ave, Auburn WA", "purchase_price": 8_750_000, "gross_rent": 720_000, "units": 40},
]


@pytest.mark.parametrize("scenario", ACQUISITION_SCENARIOS, ids=[s["address"] for s in ACQUISITION_SCENARIOS])
def test_g01_acquisition_deal_end_to_end(client, org_id, scenario):
    token = _mint_token(org_id)
    purchase_price, gross_rent = scenario["purchase_price"], scenario["gross_rent"]

    intake = client.post(
        "/api/v1/deals/intake", headers={"Authorization": f"Bearer {token}"},
        json={"property_address": scenario["address"], "source": "g01_gate_test", "org_id": org_id,
              "deal_type": "acquisition", "unit_count": scenario["units"], "asking_price": purchase_price},
    )
    assert intake.status_code == 201, intake.text
    deal_id = intake.json()["deal_id"]

    a01_out = _run_agent(client, token, deal_id, "a01", {"current_gross_rent": gross_rent}, FakeModelClient({
        "deal_id": deal_id, "deal_type_detected": "acquisition", "go_no_go": "go",
        "preliminary_cap_rate": 0.06, "preliminary_roc": None, "in_target_range": True,
        "missing_fields": [], "rationale": "Cap rate is within ZONIQ's 5.5-6.5% target range for this submarket.",
        "routing_recommendation": "route_to_a02", "confidence_score": "medium",
        "document_extraction_required": False,
    }))
    assert a01_out["output"]["go_no_go"] == "go"

    loan_amount = purchase_price * 0.75
    debt_service = compute_annual_debt_service(loan_amount, 0.065, 30)
    vacancy_amount = gross_rent * 0.07
    opex_total = gross_rent * 0.33
    noi = gross_rent - vacancy_amount - opex_total
    cap_rate = noi / purchase_price
    dscr = noi / debt_service
    coc = (noi - debt_service) / (purchase_price * 0.25)
    scen = lambda cr: {"cap_rate": cr, "dscr": dscr, "coc": coc}

    a02_out = _run_agent(client, token, deal_id, "a02", {}, FakeModelClient({
        "gross_rent": gross_rent, "vacancy_rate": 0.07, "vacancy_amount": vacancy_amount,
        "operating_expenses": {"management": opex_total * 0.3, "maintenance": opex_total * 0.2,
                                "capex_reserves": opex_total * 0.2, "insurance": opex_total * 0.1,
                                "taxes": opex_total * 0.15, "other": opex_total * 0.05},
        "noi": noi, "cap_rate": cap_rate, "dscr": dscr, "cash_on_cash": coc,
        "sensitivity_table": {
            "rent_-10pct": scen(cap_rate * 0.85), "rent_-5pct": scen(cap_rate * 0.92), "base": scen(cap_rate),
            "rent_+5pct": scen(cap_rate * 1.08), "rent_+10pct": scen(cap_rate * 1.15),
        },
        "load_bearing_assumptions": [{"assumption": "x", "why_it_matters": "y"}] * 3,
        "assumption_sources": {"gross_rent": "user_provided"}, "confidence_score": "high",
        "no_comp_disclaimer": None,
    }))
    _activate(client, token, deal_id, "a02", a02_out["snapshot_id"])

    a07_out = _run_agent(client, token, deal_id, "a07", {}, FakeModelClient({
        "memo_track": "acquisition",
        "sections": {
            "executive_summary": "x", "property_overview": "x", "market_context": "x",
            "investment_thesis": "x", "financial_summary": "x", "risk_factors": "x" * 210,
            "deal_structure": "x", "next_steps": "x",
        },
        "financial_summary_metrics": {"cap_rate": cap_rate, "noi": noi, "dscr": dscr, "cash_on_cash": coc},
        "confidence_disclosure": None, "audience_version": "internal",
    }))
    assert a07_out["output"]["memo_track"] == "acquisition"
    _activate(client, token, deal_id, "a07", a07_out["snapshot_id"])


def test_g01_land_deal_end_to_end(client, org_id):
    token = _mint_token(org_id)

    intake = client.post(
        "/api/v1/deals/intake", headers={"Authorization": f"Bearer {token}"},
        json={"property_address": "4 ZONIQ Test Land Pkwy, Puyallup WA", "source": "g01_gate_test",
              "org_id": org_id, "deal_type": "land", "land_area_sf": 40_000, "asking_price": 800_000},
    )
    assert intake.status_code == 201, intake.text
    deal_id = intake.json()["deal_id"]

    a01_out = _run_agent(client, token, deal_id, "a01", {"intended_use": "multifamily"}, FakeModelClient({
        "deal_id": deal_id, "deal_type_detected": "land", "go_no_go": "go",
        "preliminary_cap_rate": None, "preliminary_roc": None, "in_target_range": True,
        "missing_fields": [], "rationale": "Raw land parcel with clean by-right zoning, routed to A-10 for a full screen.",
        "routing_recommendation": "route_to_a10", "confidence_score": "medium",
        "document_extraction_required": False,
    }))
    assert a01_out["output"]["deal_type_detected"] == "land"

    a10_out = _run_agent(client, token, deal_id, "a10", {"intended_use": "multifamily", "zoning_info": {"by_right": True}}, FakeModelClient({
        "feasibility_recommendation": "pursue", "entitlement_path": "by_right",
        "site_risk_flags": [], "seller_archetype": "long_hold", "routing_recommendation": "route_to_a11",
        "confidence_score": "medium", "estimated_developable_units": 32,
        "estimated_land_cost_per_unit": 25_000, "entitlement_timeline_estimate_months": 4,
        "land_cost_benchmark_comparison": "In line with the org's benchmark for this submarket.",
    }))
    assert a10_out["output"]["routing_recommendation"] == "route_to_a11"

    land_cost, hard_costs, soft_costs, financing_costs, contingency = 800_000, 4_800_000, 960_000, 240_000, 400_000
    total_cost = land_cost + hard_costs + soft_costs + financing_costs + contingency
    stabilized_noi = total_cost * 0.08
    exit_cap_rate = 0.06
    equity, payoff = total_cost * 0.35, total_cost * 0.35 * (1.18 ** 3)

    a11_out = _run_agent(
        client, token, deal_id, "a11",
        {"land_cost": land_cost, "unit_count": 32, "exit_cap_rate": exit_cap_rate}, FakeModelClient({
            "total_project_cost": total_cost,
            "cost_breakdown": {"land_cost": land_cost, "hard_costs": hard_costs, "soft_costs": soft_costs,
                                "financing_costs": financing_costs, "contingency": contingency},
            "stabilized_noi": stabilized_noi, "return_on_cost": stabilized_noi / total_cost,
            "exit_cap_rate": exit_cap_rate, "development_spread": stabilized_noi / total_cost - exit_cap_rate,
            "value_destructive": False, "cash_flows": [-equity, 0, 0, payoff], "irr": 0.18,
            "construction_draw_schedule": [
                {"period": "Q1", "draw_amount": hard_costs / 4, "cumulative_drawn": hard_costs / 4},
                {"period": "Q2", "draw_amount": hard_costs / 4, "cumulative_drawn": hard_costs / 2},
                {"period": "Q3", "draw_amount": hard_costs / 4, "cumulative_drawn": hard_costs * 0.75},
                {"period": "Q4", "draw_amount": hard_costs / 4, "cumulative_drawn": hard_costs},
            ],
            "cost_overrun_sensitivity": {
                "base": {"return_on_cost": stabilized_noi / total_cost},
                "cost_overrun_5pct": {"return_on_cost": stabilized_noi / total_cost * 0.95},
                "cost_overrun_10pct": {"return_on_cost": stabilized_noi / total_cost * 0.90},
                "cost_overrun_15pct": {"return_on_cost": stabilized_noi / total_cost * 0.85},
            },
            "absorption_delay_sensitivity": {
                "base": {"return_on_cost": stabilized_noi / total_cost},
                "absorption_delay_3mo": {"return_on_cost": stabilized_noi / total_cost * 0.97},
                "absorption_delay_6mo": {"return_on_cost": stabilized_noi / total_cost * 0.94},
            },
            "risk_flags": [
                "entitlement:example detail for the gate test scenario",
                "construction_cost:example detail for the gate test scenario",
                "absorption:example detail for the gate test scenario",
                "financing:example detail for the gate test scenario",
            ],
            "confidence_score": {"overall": "medium", "entitlement_confidence": "medium", "construction_cost_confidence": "high"},
        }),
    )
    assert a11_out["output"]["value_destructive"] is False
    _activate(client, token, deal_id, "a11", a11_out["snapshot_id"])
