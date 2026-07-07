import pytest

from arx.agents.loan_math import compute_annual_debt_service
from arx.agents.scenario_modeling import (
    AcquisitionScenarioOverrides,
    DevelopmentScenarioOverrides,
    run_acquisition_scenario,
    run_development_scenario,
)

PURCHASE_PRICE = 5_000_000
LOAN_AMOUNT, LTV, INTEREST_RATE, AMORT_YEARS = 3_750_000, 0.75, 0.065, 30
BASE_DEBT_SERVICE = compute_annual_debt_service(LOAN_AMOUNT, INTEREST_RATE, AMORT_YEARS)


def _a02_baseline(**overrides):
    base = {
        "gross_rent": 500_000, "vacancy_rate": 0.07,
        "operating_expenses": {"management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
                                "insurance": 25_000, "taxes": 40_000, "other": 10_000},
        "purchase_price": PURCHASE_PRICE, "loan_amount": LOAN_AMOUNT, "ltv": LTV,
        "interest_rate": INTEREST_RATE, "amortization_years": AMORT_YEARS,
    }
    base.update(overrides)
    return base


def test_acquisition_scenario_no_overrides_matches_baseline_math():
    baseline = _a02_baseline()
    result = run_acquisition_scenario(baseline=baseline, overrides=AcquisitionScenarioOverrides())
    expected_noi = 500_000 * (1 - 0.07) - 165_000
    assert result["noi"] == pytest.approx(expected_noi)
    assert result["cap_rate"] == pytest.approx(expected_noi / PURCHASE_PRICE)
    assert result["dscr"] == pytest.approx(expected_noi / BASE_DEBT_SERVICE)


def test_acquisition_scenario_bear_case_lowers_noi_and_dscr():
    baseline = _a02_baseline()
    bear = AcquisitionScenarioOverrides(rent_change_pct=-0.08, expense_change_pct=0.05)
    baseline_result = run_acquisition_scenario(baseline=baseline, overrides=AcquisitionScenarioOverrides())
    bear_result = run_acquisition_scenario(baseline=baseline, overrides=bear)
    assert bear_result["noi"] < baseline_result["noi"]
    assert bear_result["dscr"] < baseline_result["dscr"]


def test_acquisition_scenario_flags_dscr_hard_fail():
    baseline = _a02_baseline()
    severe_bear = AcquisitionScenarioOverrides(rent_change_pct=-0.40)
    result = run_acquisition_scenario(baseline=baseline, overrides=severe_bear)
    assert result["dscr"] < 1.00
    assert result["dscr_hard_fail"] is True


def test_acquisition_scenario_interest_rate_override_changes_debt_service():
    baseline = _a02_baseline()
    result = run_acquisition_scenario(
        baseline=baseline, overrides=AcquisitionScenarioOverrides(interest_rate_override=0.08),
    )
    higher_rate_debt_service = compute_annual_debt_service(LOAN_AMOUNT, 0.08, AMORT_YEARS)
    assert result["dscr"] == pytest.approx(result["noi"] / higher_rate_debt_service)


LAND_COST, HARD_COSTS, SOFT_COSTS, FINANCING_COSTS, CONTINGENCY = 1_000_000, 6_000_000, 1_200_000, 300_000, 500_000
TOTAL_PROJECT_COST = LAND_COST + HARD_COSTS + SOFT_COSTS + FINANCING_COSTS + CONTINGENCY
STABILIZED_NOI = 720_000
EXIT_CAP_RATE = 0.06


def _a11_baseline(**overrides):
    base = {
        "cost_breakdown": {
            "land_cost": LAND_COST, "hard_costs": HARD_COSTS, "soft_costs": SOFT_COSTS,
            "financing_costs": FINANCING_COSTS, "contingency": CONTINGENCY,
        },
        "stabilized_noi": STABILIZED_NOI, "exit_cap_rate": EXIT_CAP_RATE,
    }
    base.update(overrides)
    return base


def test_development_scenario_no_overrides_matches_baseline_math():
    baseline = _a11_baseline()
    result = run_development_scenario(baseline=baseline, overrides=DevelopmentScenarioOverrides())
    assert result["total_project_cost"] == pytest.approx(TOTAL_PROJECT_COST)
    assert result["return_on_cost"] == pytest.approx(STABILIZED_NOI / TOTAL_PROJECT_COST)
    assert result["value_destructive"] is False


def test_development_scenario_bear_case_combines_all_three_overrides():
    baseline = _a11_baseline()
    bear = DevelopmentScenarioOverrides(
        construction_cost_overrun_pct=0.12, rent_change_pct=-0.08, exit_cap_rate_override=EXIT_CAP_RATE + 0.005,
    )
    result = run_development_scenario(baseline=baseline, overrides=bear)

    expected_hard_costs = HARD_COSTS * 1.12
    expected_total_cost = LAND_COST + expected_hard_costs + SOFT_COSTS + FINANCING_COSTS + CONTINGENCY
    expected_noi = STABILIZED_NOI * 0.92
    expected_roc = expected_noi / expected_total_cost

    assert result["total_project_cost"] == pytest.approx(expected_total_cost)
    assert result["return_on_cost"] == pytest.approx(expected_roc)
    assert result["exit_cap_rate"] == pytest.approx(EXIT_CAP_RATE + 0.005)
    assert result["development_spread"] == pytest.approx(expected_roc - (EXIT_CAP_RATE + 0.005))


def test_development_scenario_flags_value_destructive_when_spread_negative():
    baseline = _a11_baseline(stabilized_noi=200_000)  # already thin margin
    severe_bear = DevelopmentScenarioOverrides(
        construction_cost_overrun_pct=0.30, rent_change_pct=-0.20, exit_cap_rate_override=0.08,
    )
    result = run_development_scenario(baseline=baseline, overrides=severe_bear)
    assert result["development_spread"] < 0
    assert result["value_destructive"] is True
