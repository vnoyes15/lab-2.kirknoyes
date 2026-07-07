"""These tests prove the graph *topology* (edges, conditional routing, state threading)
correctly drives real agent logic end-to-end (Section 04) for the Phase 2 agents
(A-01, A-02, A-07, A-09) plus Phase 3/4's A-03/A-10/A-11. See arx/orchestration/nodes.py's
docstring for the scope boundary: these graphs are exercised here and available for a
future autonomous mode, but arx/api/agents.py's per-agent endpoints are the actual
production path.

Real agent nodes call get_default_model_client() internally; every test here patches
the module-level singleton to a FakeModelClient so no test ever reaches the real
Anthropic API.
"""
import pytest

import arx.agents.model_client as model_client_module
from arx.agents.loan_math import compute_annual_debt_service
from arx.orchestration.acquisition_flow import acquisition_flow
from arx.orchestration.development_flow import development_flow
from arx.orchestration.document_flow import document_flow
from arx.tests.fakes import FakeModelClient

PURCHASE_PRICE = 5_000_000
LOAN_AMOUNT, LTV, INTEREST_RATE, AMORT_YEARS = 3_750_000, 0.75, 0.065, 30
NOI = 300_000
ANNUAL_DEBT_SERVICE = compute_annual_debt_service(LOAN_AMOUNT, INTEREST_RATE, AMORT_YEARS)
DSCR = NOI / ANNUAL_DEBT_SERVICE
COC = (NOI - ANNUAL_DEBT_SERVICE) / (PURCHASE_PRICE * (1 - LTV))


@pytest.fixture
def fake_client(monkeypatch):
    fake = FakeModelClient({})  # response overwritten per-call via .responses below
    monkeypatch.setattr(model_client_module, "_default_client", fake)
    return fake


def test_document_flow_rent_roll_via_real_parser(fake_client):
    # rent_roll documents never call the model at all (arx/agents/a09_document_intelligence.py).
    csv_bytes = (
        b"unit_id,lease_start,lease_end,contracted_rent,payment_status\n"
        b"1,2025-01-01,2026-01-01,1500,current\n"
    )
    result = document_flow.invoke({
        "deal_id": "d1", "org_id": "o1",
        "_current_document": {"document_type": "rent_roll", "filename": "rr.csv", "file_bytes": csv_bytes, "doc_id": "doc-1"},
        "pending_document_ids": ["doc-1"],
    })
    assert result["agent_outputs"]["a09"]["document_type_detected"] == "rent_roll"
    assert result["pending_document_ids"] == []
    assert len(fake_client.calls) == 0


def test_acquisition_flow_chains_a01_a02_a07(fake_client):
    a01_response = {
        "deal_id": "d1", "deal_type_detected": "acquisition", "go_no_go": "go",
        "preliminary_cap_rate": 0.06, "preliminary_roc": None, "in_target_range": True,
        "missing_fields": [], "rationale": "Within ZONIQ's 5.5-6.5% target cap rate range for this submarket.",
        "routing_recommendation": "route_to_a02", "confidence_score": "medium",
        "document_extraction_required": False,
    }
    scenario = lambda cap_rate: {"cap_rate": cap_rate, "dscr": DSCR, "coc": COC}
    a02_response = {
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
    a07_response = {
        "memo_track": "acquisition",
        "sections": {
            "executive_summary": "x", "property_overview": "x", "market_context": "x",
            "investment_thesis": "x", "financial_summary": "x", "risk_factors": "x" * 210,
            "deal_structure": "x", "next_steps": "x",
        },
        "financial_summary_metrics": {"cap_rate": NOI / PURCHASE_PRICE, "noi": NOI, "dscr": DSCR, "cash_on_cash": COC},
        "confidence_disclosure": None, "audience_version": "internal",
    }

    responses = iter([a01_response, a02_response, a07_response])
    fake_client.generate_json = lambda *a, **k: FakeModelClient(next(responses)).generate_json(*a, **k)

    result = acquisition_flow.invoke({
        "deal_id": "d1", "org_id": "o1", "property_address": "123 Main St, Tacoma WA",
        "asking_price": PURCHASE_PRICE, "unit_count": 24, "land_area_sf": None,
        "current_gross_rent": 500_000, "intended_use": None,
        "target_cap_rate_range": (0.055, 0.065), "target_roc_range": None,
        "purchase_price": PURCHASE_PRICE, "asset_type": "multifamily", "submarket": "Tacoma, WA",
        "uw_defaults": {"vacancy": 0.07}, "loan_amount": LOAN_AMOUNT, "ltv": LTV,
        "interest_rate": INTEREST_RATE, "amortization_years": AMORT_YEARS, "comps": None,
        "audience_version": "internal",
    })

    assert result.get("terminated") is not True
    assert result["deal_type"] == "acquisition"
    assert result["agent_outputs"]["a01"]["go_no_go"] == "go"
    assert result["agent_outputs"]["a02"]["cap_rate"] == pytest.approx(0.06)
    assert result["agent_outputs"]["a07"]["memo_track"] == "acquisition"


def test_acquisition_flow_no_go_terminates_before_a02(fake_client):
    fake_client.generate_json = lambda *a, **k: FakeModelClient({
        "deal_id": "d1", "deal_type_detected": "acquisition", "go_no_go": "no_go",
        "preliminary_cap_rate": 0.03, "preliminary_roc": None, "in_target_range": False,
        "missing_fields": [], "rationale": "Cap rate of 3.0% is far below ZONIQ's 5.5-6.5% target range.",
        "routing_recommendation": "no_go_end", "confidence_score": "high",
        "document_extraction_required": False,
    }).generate_json(*a, **k)

    result = acquisition_flow.invoke({
        "deal_id": "d1", "org_id": "o1", "property_address": "999 Overpriced Ave",
        "asking_price": 10_000_000, "target_cap_rate_range": (0.055, 0.065), "target_roc_range": None,
    })

    assert "a02" not in result.get("agent_outputs", {})


LAND_COST = 800_000
HARD_COSTS = 4_800_000
SOFT_COSTS = 960_000
FINANCING_COSTS = 240_000
CONTINGENCY = 400_000
TOTAL_PROJECT_COST = LAND_COST + HARD_COSTS + SOFT_COSTS + FINANCING_COSTS + CONTINGENCY
STABILIZED_NOI = TOTAL_PROJECT_COST * 0.08
RETURN_ON_COST = STABILIZED_NOI / TOTAL_PROJECT_COST
EXIT_CAP_RATE = 0.06
DEVELOPMENT_SPREAD = RETURN_ON_COST - EXIT_CAP_RATE
EQUITY = 3_000_000
PAYOFF = EQUITY * (1.20 ** 3)


def _a11_response(**overrides):
    base = {
        "total_project_cost": TOTAL_PROJECT_COST,
        "cost_breakdown": {
            "land_cost": LAND_COST, "hard_costs": HARD_COSTS, "soft_costs": SOFT_COSTS,
            "financing_costs": FINANCING_COSTS, "contingency": CONTINGENCY,
        },
        "stabilized_noi": STABILIZED_NOI, "return_on_cost": RETURN_ON_COST, "exit_cap_rate": EXIT_CAP_RATE,
        "development_spread": DEVELOPMENT_SPREAD, "value_destructive": False,
        "cash_flows": [-EQUITY, 0, 0, PAYOFF], "irr": 0.20,
        "construction_draw_schedule": [
            {"period": "Q1", "draw_amount": 1_200_000, "cumulative_drawn": 1_200_000},
            {"period": "Q2", "draw_amount": 1_200_000, "cumulative_drawn": 2_400_000},
            {"period": "Q3", "draw_amount": 1_200_000, "cumulative_drawn": 3_600_000},
            {"period": "Q4", "draw_amount": 1_200_000, "cumulative_drawn": 4_800_000},
        ],
        "cost_overrun_sensitivity": {
            "base": {"return_on_cost": 0.08}, "cost_overrun_5pct": {"return_on_cost": 0.076},
            "cost_overrun_10pct": {"return_on_cost": 0.072}, "cost_overrun_15pct": {"return_on_cost": 0.068},
        },
        "absorption_delay_sensitivity": {
            "base": {"return_on_cost": 0.08}, "absorption_delay_3mo": {"return_on_cost": 0.078},
            "absorption_delay_6mo": {"return_on_cost": 0.075},
        },
        "risk_flags": [
            "entitlement:conditional use permit still pending city council vote",
            "construction_cost:steel pricing has been volatile in this market",
            "absorption:two comparable projects are delivering units in the same window",
            "financing:construction loan rate lock expires before permits are expected",
        ],
        "confidence_score": {"overall": "medium", "entitlement_confidence": "medium", "construction_cost_confidence": "high"},
    }
    base.update(overrides)
    return base


def test_development_flow_direct_development_chains_a01_a11(fake_client):
    a01_response = {
        "deal_id": "d2", "deal_type_detected": "development", "go_no_go": "go",
        "preliminary_cap_rate": None, "preliminary_roc": 0.09, "in_target_range": True,
        "missing_fields": [], "rationale": "Return on cost estimate exceeds the org's development threshold.",
        "routing_recommendation": "route_to_a10", "confidence_score": "medium",
        "document_extraction_required": False,
    }
    responses = iter([a01_response, _a11_response()])
    fake_client.generate_json = lambda *a, **k: FakeModelClient(next(responses)).generate_json(*a, **k)

    result = development_flow.invoke({
        "deal_id": "d2", "org_id": "o1", "property_address": "Vacant lot, Auburn WA",
        "asking_price": LAND_COST, "deal_type": "development",
        "target_cap_rate_range": None, "target_roc_range": (0.15, 0.20),
        "dev_defaults": {"soft_costs_pct_of_hard_min": 0.15, "soft_costs_pct_of_hard_max": 0.20},
        "exit_cap_rate": EXIT_CAP_RATE, "unit_count": 32,
    })

    assert result.get("terminated") is not True
    assert result["agent_outputs"]["a01"]["go_no_go"] == "go"
    assert result["agent_outputs"]["a11"]["value_destructive"] is False


def test_development_flow_land_chains_a01_a10_a11(fake_client):
    a01_response = {
        "deal_id": "d3", "deal_type_detected": "land", "go_no_go": "go",
        "preliminary_cap_rate": None, "preliminary_roc": None, "in_target_range": True,
        "missing_fields": [], "rationale": "Raw land parcel with unresolved entitlement status, routed to A-10 for a full feasibility screen.",
        "routing_recommendation": "route_to_a10", "confidence_score": "medium",
        "document_extraction_required": False,
    }
    a10_response = {
        "feasibility_recommendation": "pursue", "entitlement_path": "by_right",
        "site_risk_flags": [], "seller_archetype": "long_hold", "routing_recommendation": "route_to_a11",
        "confidence_score": "medium", "estimated_developable_units": 32,
        "estimated_land_cost_per_unit": 25_000, "entitlement_timeline_estimate_months": 4,
        "land_cost_benchmark_comparison": "In line with the org's $25,000/unit benchmark.",
    }
    responses = iter([a01_response, a10_response, _a11_response()])
    fake_client.generate_json = lambda *a, **k: FakeModelClient(next(responses)).generate_json(*a, **k)

    result = development_flow.invoke({
        "deal_id": "d3", "org_id": "o1", "property_address": "Vacant lot, Kent WA",
        "asking_price": LAND_COST, "land_area_sf": 40_000, "deal_type": "land",
        "intended_use": "multifamily", "target_cap_rate_range": None, "target_roc_range": (0.15, 0.20),
        "dev_defaults": {"soft_costs_pct_of_hard_min": 0.15, "soft_costs_pct_of_hard_max": 0.20},
        "exit_cap_rate": EXIT_CAP_RATE, "unit_count": 32,
    })

    assert result.get("terminated") is not True
    assert result["agent_outputs"]["a10"]["routing_recommendation"] == "route_to_a11"
    assert result["agent_outputs"]["a11"]["value_destructive"] is False


def test_development_flow_land_no_go_terminates_before_a11(fake_client):
    a01_response = {
        "deal_id": "d4", "deal_type_detected": "land", "go_no_go": "go",
        "preliminary_cap_rate": None, "preliminary_roc": None, "in_target_range": True,
        "missing_fields": [], "rationale": "Raw land parcel with unresolved entitlement status, routed to A-10 for a full feasibility screen.",
        "routing_recommendation": "route_to_a10", "confidence_score": "medium",
        "document_extraction_required": False,
    }
    a10_response = {
        "feasibility_recommendation": "pass", "entitlement_path": "rezoning_required",
        "site_risk_flags": ["political_entitlement_risk"], "seller_archetype": "municipality",
        "routing_recommendation": "pass_end", "confidence_score": "medium",
        "estimated_developable_units": None, "estimated_land_cost_per_unit": None,
        "entitlement_timeline_estimate_months": None, "land_cost_benchmark_comparison": None,
    }
    responses = iter([a01_response, a10_response])
    fake_client.generate_json = lambda *a, **k: FakeModelClient(next(responses)).generate_json(*a, **k)

    result = development_flow.invoke({
        "deal_id": "d4", "org_id": "o1", "property_address": "City-owned parcel",
        "asking_price": None, "land_area_sf": 20_000, "deal_type": "land",
        "target_cap_rate_range": None, "target_roc_range": (0.15, 0.20),
    })

    assert "a11" not in result.get("agent_outputs", {})
