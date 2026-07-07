import pytest

from arx.agents.a11_development_pro_forma import A11ValidationError, run_a11
from arx.tests.fakes import FakeModelClient

LAND_COST = 1_000_000
HARD_COSTS = 6_000_000
SOFT_COSTS = 1_200_000
FINANCING_COSTS = 300_000
CONTINGENCY = 500_000
TOTAL_PROJECT_COST = LAND_COST + HARD_COSTS + SOFT_COSTS + FINANCING_COSTS + CONTINGENCY  # 9,000,000

STABILIZED_NOI = 720_000
RETURN_ON_COST = STABILIZED_NOI / TOTAL_PROJECT_COST  # 0.08
EXIT_CAP_RATE = 0.06
DEVELOPMENT_SPREAD = RETURN_ON_COST - EXIT_CAP_RATE  # 0.02

EQUITY = 3_000_000
PAYOFF = EQUITY * (1.20 ** 3)


def _consistent_response(**overrides):
    base = {
        "total_project_cost": TOTAL_PROJECT_COST,
        "cost_breakdown": {
            "land_cost": LAND_COST, "hard_costs": HARD_COSTS, "soft_costs": SOFT_COSTS,
            "financing_costs": FINANCING_COSTS, "contingency": CONTINGENCY,
        },
        "stabilized_noi": STABILIZED_NOI,
        "return_on_cost": RETURN_ON_COST,
        "exit_cap_rate": EXIT_CAP_RATE,
        "development_spread": DEVELOPMENT_SPREAD,
        "value_destructive": False,
        "cash_flows": [-EQUITY, 0, 0, PAYOFF],
        "irr": 0.20,
        "construction_draw_schedule": [
            {"period": "Q1", "draw_amount": 1_800_000, "cumulative_drawn": 1_800_000},
            {"period": "Q2", "draw_amount": 1_800_000, "cumulative_drawn": 3_600_000},
            {"period": "Q3", "draw_amount": 1_800_000, "cumulative_drawn": 5_400_000},
            {"period": "Q4", "draw_amount": 1_800_000, "cumulative_drawn": 7_200_000},
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


def _run(response, **overrides):
    fake = FakeModelClient(response, input_tokens=900, output_tokens=700)
    kwargs = dict(
        land_cost=LAND_COST, unit_count=32, asset_type="multifamily",
        dev_defaults={"soft_costs_pct_of_hard_min": 0.15, "soft_costs_pct_of_hard_max": 0.20},
        exit_cap_rate=EXIT_CAP_RATE, model_client=fake,
    )
    kwargs.update(overrides)
    return run_a11(**kwargs), fake


def test_run_a11_consistent_output_passes_validation():
    result, fake = _run(_consistent_response())
    assert result.validation.passed
    assert result.output.value_destructive is False
    assert len(fake.calls) == 1


def test_run_a11_negative_spread_must_be_flagged():
    bad = _consistent_response(
        return_on_cost=0.05, development_spread=0.05 - EXIT_CAP_RATE, value_destructive=False,
        stabilized_noi=0.05 * TOTAL_PROJECT_COST,
    )
    with pytest.raises(A11ValidationError) as excinfo:
        _run(bad)
    failed_ids = {c["check_id"] for c in excinfo.value.failed_checks["checks"] if not c["passed"]}
    assert "DV2" in failed_ids


def test_run_a11_rejects_inconsistent_total_project_cost():
    bad = _consistent_response(total_project_cost=99_000_000)
    with pytest.raises(A11ValidationError) as excinfo:
        _run(bad)
    failed_ids = {c["check_id"] for c in excinfo.value.failed_checks["checks"] if not c["passed"]}
    assert "DV3" in failed_ids


def test_run_a11_rejects_non_monotonic_absorption_sensitivity():
    bad = _consistent_response(absorption_delay_sensitivity={
        "base": {"return_on_cost": 0.08},
        "absorption_delay_3mo": {"return_on_cost": 0.09},  # worse assumption showing a BETTER return
        "absorption_delay_6mo": {"return_on_cost": 0.075},
    })
    with pytest.raises(A11ValidationError) as excinfo:
        _run(bad)
    failed_ids = {c["check_id"] for c in excinfo.value.failed_checks["checks"] if not c["passed"]}
    assert "MV5" in failed_ids  # absorption axis reuses the generic directional-check primitive


def test_run_a11_rejects_missing_risk_category():
    bad = _consistent_response(risk_flags=[
        "entitlement:a", "entitlement:b", "entitlement:c", "entitlement:d",
    ])
    fake = FakeModelClient(bad)
    with pytest.raises(A11ValidationError, match="schema validation"):
        run_a11(
            land_cost=LAND_COST, unit_count=32, asset_type="multifamily", dev_defaults={},
            exit_cap_rate=EXIT_CAP_RATE, model_client=fake,
        )


def test_run_a11_rejects_short_construction_draw_missing_field():
    bad = _consistent_response()
    del bad["construction_draw_schedule"][0]["cumulative_drawn"]
    fake = FakeModelClient(bad)
    with pytest.raises(A11ValidationError, match="schema validation"):
        run_a11(
            land_cost=LAND_COST, unit_count=32, asset_type="multifamily", dev_defaults={},
            exit_cap_rate=EXIT_CAP_RATE, model_client=fake,
        )


def test_run_a11_sends_dev_defaults_to_model():
    _, fake = _run(_consistent_response())
    assert "soft_costs_pct_of_hard" in fake.calls[0]["user_message"]
