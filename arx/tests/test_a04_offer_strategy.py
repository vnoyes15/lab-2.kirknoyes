import pytest

from arx.agents.a04_offer_strategy import A04ValidationError, run_a04
from arx.tests.fakes import FakeModelClient


def _strategy(price, **overrides):
    base = {
        "purchase_price": price,
        "financing_structure": "Standard bank financing, 75% LTV.",
        "seller_rationale": "Seller is a distressed owner facing tax delinquency and likely to accept a faster, "
                             "as-is close at a modest discount to asking.",
        "zoniq_returns": {"cap_rate": 300_000 / price, "dscr": 1.2, "coc": 0.04},
        "key_risks": ["Rent roll accuracy unverified.", "Submarket comps are 90+ days old."],
    }
    base.update(overrides)
    return base


def _response(**overrides):
    base = {
        "strategies": [
            _strategy(4_700_000),
            _strategy(4_900_000),
            _strategy(5_000_000),
        ],
        "feasibility_contingency_days": None,
    }
    base.update(overrides)
    return base


def test_run_a04_acquisition_produces_three_strategies():
    fake = FakeModelClient(_response())
    result = run_a04(
        deal_type="acquisition",
        underwriting_snapshot={"noi": 300_000, "cap_rate": 0.06, "purchase_price": 5_000_000},
        seller_profile={"seller_archetype": "distressed", "motivated_seller_score": 78},
        model_client=fake,
    )
    assert len(result.output.strategies) == 3
    assert result.output.strategies[0].purchase_price == 4_700_000
    assert result.output.strategies[2].purchase_price == 5_000_000


def test_run_a04_land_requires_feasibility_contingency_days():
    fake = FakeModelClient(_response(feasibility_contingency_days=None))
    with pytest.raises(A04ValidationError, match="feasibility_contingency_days"):
        run_a04(
            deal_type="land",
            underwriting_snapshot={"preliminary_roc": 0.09},
            seller_profile={"seller_archetype": "family_trust"},
            feasibility_contingency_days_default=75,
            model_client=fake,
        )


def test_run_a04_land_with_feasibility_days_passes():
    fake = FakeModelClient(_response(feasibility_contingency_days=75))
    result = run_a04(
        deal_type="land",
        underwriting_snapshot={"preliminary_roc": 0.09},
        seller_profile={"seller_archetype": "family_trust"},
        feasibility_contingency_days_default=75,
        model_client=fake,
    )
    assert result.output.feasibility_contingency_days == 75


def test_run_a04_rejects_fewer_than_two_risks():
    bad = _response()
    bad["strategies"][0]["key_risks"] = ["only one risk"]
    fake = FakeModelClient(bad)
    with pytest.raises(A04ValidationError, match="schema validation"):
        run_a04(
            deal_type="acquisition", underwriting_snapshot={}, seller_profile={}, model_client=fake,
        )


def test_run_a04_rejects_wrong_number_of_strategies():
    bad = _response()
    bad["strategies"] = bad["strategies"][:2]
    fake = FakeModelClient(bad)
    with pytest.raises(A04ValidationError):
        run_a04(deal_type="acquisition", underwriting_snapshot={}, seller_profile={}, model_client=fake)


def test_run_a04_sends_seller_profile_to_model():
    fake = FakeModelClient(_response())
    run_a04(
        deal_type="acquisition", underwriting_snapshot={"noi": 300_000},
        seller_profile={"seller_archetype": "distressed"}, model_client=fake,
    )
    assert "distressed" in fake.calls[0]["user_message"]
