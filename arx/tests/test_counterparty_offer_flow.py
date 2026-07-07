"""Proves the counterparty_offer_flow.py topology (a03 -> a04 -> a05) correctly
drives real Phase 3 agent logic end-to-end, and that a12_node works as the standalone
node it's designed to be (Section 42 — see arx/orchestration/nodes.py docstring).
Every test patches the model_client singleton to a FakeModelClient; none ever reaches
the real Anthropic API.
"""
import pytest

import arx.agents.model_client as model_client_module
from arx.orchestration.counterparty_offer_flow import counterparty_offer_flow
from arx.orchestration.nodes import a12_node
from arx.tests.fakes import FakeModelClient


@pytest.fixture
def fake_client(monkeypatch):
    fake = FakeModelClient({})
    monkeypatch.setattr(model_client_module, "_default_client", fake)
    return fake


def test_counterparty_offer_flow_chains_a03_a04_a05(fake_client):
    a03_response = {
        "seller_archetype": "distressed",
        "distress_indicators": ["tax delinquency"],
        "motivated_seller_score": 75,
        "outreach_approach": "Approach directly and briefly, emphasizing a fast as-is close given apparent "
                             "tax pressure on the owner.",
        "topics_to_avoid": ["Do not mention the tax lien directly."],
        "confidence_score": "medium",
    }
    strategy = lambda price: {
        "purchase_price": price, "financing_structure": "Standard bank financing.",
        "seller_rationale": "Seller is distressed and motivated by tax delinquency, likely to accept a fast, "
                             "as-is close below asking.",
        "zoniq_returns": {"cap_rate": 300_000 / price, "dscr": 1.2, "coc": 0.04},
        "key_risks": ["Rent roll unverified.", "Comps are dated."],
    }
    a04_response = {
        "strategies": [strategy(4_700_000), strategy(4_900_000), strategy(5_000_000)],
        "feasibility_contingency_days": None,
    }
    a05_response = {
        "loi_text": "x" * 520,
        "attorney_review_warning": "Buyer's attorney must review this LOI before execution. Unconditional.",
        "escrow_reference_present": True,
        "jurisdiction_flags": ["wa_rent_control_rcw59_18"],
    }

    responses = iter([a03_response, a04_response, a05_response])
    fake_client.generate_json = lambda *a, **k: FakeModelClient(next(responses)).generate_json(*a, **k)

    result = counterparty_offer_flow.invoke({
        "deal_id": "d1", "org_id": "o1", "deal_type": "acquisition",
        "property_address": "123 Main St, Tacoma WA",
        "agent_outputs": {"a02": {"noi": 300_000, "cap_rate": 0.06}},
        "state_code": "WA",
        "org_jurisdiction": {"rent_control_active": True},
        "_selected_strategy_index": 1,  # the "middle" strategy
    })

    assert result.get("terminated") is not True
    assert result["agent_outputs"]["a03"]["seller_archetype"] == "distressed"
    assert result["agent_outputs"]["a04"]["strategies"][1]["purchase_price"] == 4_900_000
    assert result["agent_outputs"]["a05"]["escrow_reference_present"] is True


def test_counterparty_offer_flow_a03_failure_halts_before_a04(fake_client):
    # Schema violation: outreach_approach too short.
    fake_client.generate_json = lambda *a, **k: FakeModelClient({
        "seller_archetype": "distressed", "distress_indicators": [],
        "motivated_seller_score": 50, "outreach_approach": "too short",
        "topics_to_avoid": ["x"], "confidence_score": "low",
    }).generate_json(*a, **k)

    result = counterparty_offer_flow.invoke({
        "deal_id": "d1", "org_id": "o1", "deal_type": "acquisition",
        "property_address": "123 Main St", "agent_outputs": {"a02": {"noi": 300_000}},
        "state_code": "WA", "org_jurisdiction": {}, "_selected_strategy_index": 0,
    })

    assert result["terminated"] is True
    assert "a04" not in result.get("agent_outputs", {})
    assert "a05" not in result.get("agent_outputs", {})


def test_a12_node_standalone_negotiation_support(fake_client):
    fake_client.generate_json = lambda *a, **k: FakeModelClient({
        "counter_analysis": "The seller's counter is a modest $100,000 above our offer, suggesting they remain "
                             "anchored near asking but are showing real flexibility toward a negotiated middle ground.",
        "deal_impact": {"cap_rate_delta": -0.001, "dscr_delta": -0.01, "coc_delta": -0.001},
        "response_options": [
            {"label": "hold_firm", "description": "x", "return_impact": {"cap_rate": 0.06}, "recommended": False},
            {"label": "partial_concession", "description": "x", "return_impact": {"cap_rate": 0.059}, "recommended": True},
            {"label": "accept_counter", "description": "x", "return_impact": {"cap_rate": 0.058}, "recommended": False},
        ],
        "recommendation_rationale": "Given the seller's apparent flexibility and a comparable deal that closed "
                                     "near the midpoint last quarter, a partial concession keeps our returns "
                                     "within threshold while likely securing the deal without further delay.",
        "below_threshold_flag": False,
    }).generate_json(*a, **k)

    state = {
        "deal_id": "d1", "org_id": "o1",
        "agent_outputs": {"a02": {"noi": 300_000, "cap_rate": 0.06}},
        "original_offer_strategy": {"purchase_price": 4_900_000},
        "seller_counter_terms": {"purchase_price": 5_000_000},
    }
    result = a12_node(state)
    assert result["agent_outputs"]["a12"]["below_threshold_flag"] is False


def test_a12_node_requires_active_a02_output():
    with pytest.raises(ValueError, match="a02"):
        a12_node({"deal_id": "d1", "org_id": "o1", "original_offer_strategy": {}, "seller_counter_terms": {}})
