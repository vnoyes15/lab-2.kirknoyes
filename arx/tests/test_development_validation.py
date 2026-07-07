from arx.validation.development_validation import (
    check_development_spread,
    check_irr_consistency,
    check_return_on_cost_consistency,
    check_total_project_cost,
    validate_development_output,
)


def test_return_on_cost_consistency():
    result = check_return_on_cost_consistency(stabilized_noi=720_000, total_project_cost=9_000_000, reported_roc=0.08)
    assert result.passed


def test_development_spread_positive_not_flagged():
    result = check_development_spread(
        return_on_cost=0.08, exit_cap_rate=0.06, reported_spread=0.02, value_destructive_flag=False
    )
    assert result.passed


def test_development_spread_negative_must_be_flagged():
    # Section 15 DV2: "Negative spread = value-destructive development, flag prominently."
    result = check_development_spread(
        return_on_cost=0.05, exit_cap_rate=0.06, reported_spread=-0.01, value_destructive_flag=True
    )
    assert result.passed


def test_development_spread_negative_but_not_flagged_fails():
    result = check_development_spread(
        return_on_cost=0.05, exit_cap_rate=0.06, reported_spread=-0.01, value_destructive_flag=False
    )
    assert not result.passed
    assert result.check_id == "DV2"


def test_total_project_cost_construction():
    result = check_total_project_cost(
        land_cost=1_000_000, hard_costs=6_000_000, soft_costs=1_200_000,
        financing_costs=300_000, contingency=500_000, reported_total_project_cost=9_000_000,
    )
    assert result.passed


def test_irr_consistency_three_year_hold():
    # -1,000,000 at t=0, single payoff at t=3 sized for exactly 20% IRR.
    payoff = 1_000_000 * (1.20 ** 3)
    cash_flows = [-1_000_000, 0, 0, payoff]
    result = check_irr_consistency(cash_flows, reported_irr=0.20)
    assert result.passed, result.message


def test_irr_consistency_catches_mismatch():
    payoff = 1_000_000 * (1.20 ** 3)
    cash_flows = [-1_000_000, 0, 0, payoff]
    result = check_irr_consistency(cash_flows, reported_irr=0.35)
    assert not result.passed
    assert result.check_id == "DV4"


def test_validate_development_output_all_consistent():
    payoff = 1_000_000 * (1.20 ** 3)
    output = {
        "stabilized_noi": 720_000,
        "total_project_cost": 9_000_000,
        "return_on_cost": 0.08,
        "exit_cap_rate": 0.06,
        "development_spread": 0.02,
        "value_destructive": False,
        "cost_breakdown": {
            "land_cost": 1_000_000, "hard_costs": 6_000_000, "soft_costs": 1_200_000,
            "financing_costs": 300_000, "contingency": 500_000,
        },
        "cash_flows": [-1_000_000, 0, 0, payoff],
        "irr": 0.20,
    }
    suite = validate_development_output(output)
    assert suite.passed, suite.to_dict()
