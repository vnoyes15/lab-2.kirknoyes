"""Section 07 Phase 5 "full state management, handoffs" — proves
acquisition_flow_with_checkpoint actually pauses at the a02->a07 boundary and only
proceeds on an explicit resume, modeling Section 13/R5's human snapshot-activation
checkpoint at the graph level (not just documented as an API-layer convention).

Real agent nodes call get_default_model_client() internally; this test patches the
module-level singleton to a FakeModelClient, same pattern as test_orchestration_flows.py.
"""
import pytest

import arx.agents.model_client as model_client_module
from arx.agents.loan_math import compute_annual_debt_service
from arx.orchestration.acquisition_flow import acquisition_flow_with_checkpoint
from arx.tests.fakes import FakeModelClient

PURCHASE_PRICE = 5_000_000
LOAN_AMOUNT, LTV, INTEREST_RATE, AMORT_YEARS = 3_750_000, 0.75, 0.065, 30
NOI = 300_000
ANNUAL_DEBT_SERVICE = compute_annual_debt_service(LOAN_AMOUNT, INTEREST_RATE, AMORT_YEARS)
DSCR = NOI / ANNUAL_DEBT_SERVICE
COC = (NOI - ANNUAL_DEBT_SERVICE) / (PURCHASE_PRICE * (1 - LTV))


@pytest.fixture
def fake_client(monkeypatch):
    fake = FakeModelClient({})
    monkeypatch.setattr(model_client_module, "_default_client", fake)
    return fake


def _a01_response():
    return {
        "deal_id": "d1", "deal_type_detected": "acquisition", "go_no_go": "go",
        "preliminary_cap_rate": 0.06, "preliminary_roc": None, "in_target_range": True,
        "missing_fields": [], "rationale": "Within ZONIQ's 5.5-6.5% target cap rate range for this submarket.",
        "routing_recommendation": "route_to_a02", "confidence_score": "medium",
        "document_extraction_required": False,
    }


def _a02_response():
    scenario = lambda cap_rate: {"cap_rate": cap_rate, "dscr": DSCR, "coc": COC}
    return {
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


def _a07_response():
    return {
        "memo_track": "acquisition",
        "sections": {
            "executive_summary": "x", "property_overview": "x", "market_context": "x",
            "investment_thesis": "x", "financial_summary": "x", "risk_factors": "x" * 210,
            "deal_structure": "x", "next_steps": "x",
        },
        "financial_summary_metrics": {"cap_rate": NOI / PURCHASE_PRICE, "noi": NOI, "dscr": DSCR, "cash_on_cash": COC},
        "confidence_disclosure": None, "audience_version": "internal",
    }


def _initial_state():
    return {
        "deal_id": "d1", "org_id": "o1", "property_address": "123 Main St, Tacoma WA",
        "asking_price": PURCHASE_PRICE, "unit_count": 24, "land_area_sf": None,
        "current_gross_rent": 500_000, "intended_use": None,
        "target_cap_rate_range": (0.055, 0.065), "target_roc_range": None,
        "purchase_price": PURCHASE_PRICE, "asset_type": "multifamily", "submarket": "Tacoma, WA",
        "uw_defaults": {"vacancy": 0.07}, "loan_amount": LOAN_AMOUNT, "ltv": LTV,
        "interest_rate": INTEREST_RATE, "amortization_years": AMORT_YEARS, "comps": None,
        "audience_version": "internal",
    }


def test_graph_pauses_before_a07_until_explicit_resume(fake_client):
    responses = iter([_a01_response(), _a02_response()])
    fake_client.generate_json = lambda *a, **k: FakeModelClient(next(responses)).generate_json(*a, **k)

    config = {"configurable": {"thread_id": "deal-d1"}}
    result = acquisition_flow_with_checkpoint.invoke(_initial_state(), config)

    # a01 and a02 ran; a07 did not — the graph is paused at the interrupt point,
    # exactly mirroring "a02 wrote an inactive snapshot; nothing downstream may
    # consume it until a human explicitly activates it" (Section 13/R5).
    assert result["agent_outputs"]["a01"]["go_no_go"] == "go"
    assert result["agent_outputs"]["a02"]["cap_rate"] == pytest.approx(0.06)
    assert "a07" not in result["agent_outputs"]

    state = acquisition_flow_with_checkpoint.get_state(config)
    assert state.next == ("a07",)  # confirms the graph is paused, not finished


def test_resume_after_activation_runs_a07(fake_client):
    responses = iter([_a01_response(), _a02_response(), _a07_response()])
    fake_client.generate_json = lambda *a, **k: FakeModelClient(next(responses)).generate_json(*a, **k)

    config = {"configurable": {"thread_id": "deal-d2"}}
    acquisition_flow_with_checkpoint.invoke(_initial_state(), config)

    # The human-activation step happens here, out-of-band (in production: the
    # /agents/a02/snapshots/{id}/activate API call) — modeled as simply resuming the
    # same paused thread with no new input, since the checkpointed state already holds
    # everything a07 needs.
    result = acquisition_flow_with_checkpoint.invoke(None, config)

    assert result["agent_outputs"]["a07"]["memo_track"] == "acquisition"
    state = acquisition_flow_with_checkpoint.get_state(config)
    assert state.next == ()  # graph has run to completion


def test_paused_threads_are_independent(fake_client):
    """Two different deals paused concurrently don't leak state into each other —
    thread_id isolation is what makes the checkpoint safe to use per-deal."""
    responses = iter([_a01_response(), _a02_response(), _a01_response(), _a02_response()])
    fake_client.generate_json = lambda *a, **k: FakeModelClient(next(responses)).generate_json(*a, **k)

    config_a = {"configurable": {"thread_id": "deal-a"}}
    config_b = {"configurable": {"thread_id": "deal-b"}}
    acquisition_flow_with_checkpoint.invoke(_initial_state(), config_a)
    acquisition_flow_with_checkpoint.invoke(_initial_state(), config_b)

    assert acquisition_flow_with_checkpoint.get_state(config_a).next == ("a07",)
    assert acquisition_flow_with_checkpoint.get_state(config_b).next == ("a07",)
