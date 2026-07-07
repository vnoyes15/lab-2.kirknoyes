import pytest

from arx.agents.a12_negotiation_support import A12ValidationError, run_a12
from arx.tests.fakes import FakeModelClient


def _response(**overrides):
    base = {
        "counter_analysis": "The seller's counter of $5,100,000 against our $4,900,000 offer, a modest $200,000 "
                             "gap, suggests they are anchored near asking but open to negotiation given the "
                             "distress signals in their profile.",
        "deal_impact": {"cap_rate_delta": -0.0025, "dscr_delta": -0.02, "coc_delta": -0.003},
        "response_options": [
            {"label": "hold_firm", "description": "Reject the counter, hold at $4,900,000.",
             "return_impact": {"cap_rate": 0.06, "dscr": 1.2, "coc": 0.04}, "recommended": False},
            {"label": "partial_concession", "description": "Meet at $5,000,000.",
             "return_impact": {"cap_rate": 0.0588, "dscr": 1.18, "coc": 0.038}, "recommended": True},
            {"label": "accept_counter", "description": "Accept $5,100,000 as proposed.",
             "return_impact": {"cap_rate": 0.0577, "dscr": 1.16, "coc": 0.036}, "recommended": False},
        ],
        "recommendation_rationale": "Given the seller's distressed archetype and a comparable deal in this "
                                     "submarket that closed 3% below initial counter, a partial concession at "
                                     "$5,000,000 keeps returns within threshold while likely securing the deal "
                                     "without further delay.",
        "below_threshold_flag": False,
    }
    base.update(overrides)
    return base


def test_run_a12_valid_response():
    fake = FakeModelClient(_response())
    result = run_a12(
        original_offer_strategy={"purchase_price": 4_900_000},
        seller_counter_terms={"purchase_price": 5_100_000},
        underwriting_snapshot={"noi": 300_000, "cap_rate": 0.06},
        seller_profile={"seller_archetype": "distressed"},
        model_client=fake,
    )
    assert result.output.response_options[1].recommended is True
    assert sum(o.recommended for o in result.output.response_options) == 1


def test_run_a12_rejects_zero_recommended():
    bad = _response()
    for opt in bad["response_options"]:
        opt["recommended"] = False
    fake = FakeModelClient(bad)
    with pytest.raises(A12ValidationError, match="Exactly one"):
        run_a12(
            original_offer_strategy={}, seller_counter_terms={}, underwriting_snapshot={}, model_client=fake,
        )


def test_run_a12_rejects_two_recommended():
    bad = _response()
    bad["response_options"][0]["recommended"] = True
    bad["response_options"][1]["recommended"] = True
    fake = FakeModelClient(bad)
    with pytest.raises(A12ValidationError, match="Exactly one"):
        run_a12(
            original_offer_strategy={}, seller_counter_terms={}, underwriting_snapshot={}, model_client=fake,
        )


def test_run_a12_rejects_short_recommendation_rationale():
    bad = _response(recommendation_rationale="too short")
    fake = FakeModelClient(bad)
    with pytest.raises(A12ValidationError, match="schema validation"):
        run_a12(
            original_offer_strategy={}, seller_counter_terms={}, underwriting_snapshot={}, model_client=fake,
        )


def test_run_a12_below_threshold_flag_passthrough():
    fake = FakeModelClient(_response(below_threshold_flag=True))
    result = run_a12(
        original_offer_strategy={}, seller_counter_terms={}, underwriting_snapshot={}, model_client=fake,
    )
    assert result.output.below_threshold_flag is True
