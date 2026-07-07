import pytest

from arx.agents.loan_math import compute_annual_debt_service
from arx.agents.portfolio_stress import (
    StressParams,
    stress_acquisition_asset,
    stress_development_asset,
    summarize_portfolio_stress,
)

PURCHASE_PRICE = 5_000_000
LOAN_AMOUNT, INTEREST_RATE, AMORT_YEARS = 3_750_000, 0.065, 30
NOI = 300_000
BASE_DEBT_SERVICE = compute_annual_debt_service(LOAN_AMOUNT, INTEREST_RATE, AMORT_YEARS)


def _a02_baseline(**overrides):
    base = {
        "gross_rent": 500_000, "vacancy_rate": 0.07,
        "operating_expenses": {"management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
                                "insurance": 25_000, "taxes": 40_000, "other": 10_000},
        "noi": NOI, "cap_rate": NOI / PURCHASE_PRICE,
        "loan_amount": LOAN_AMOUNT, "interest_rate": INTEREST_RATE, "amortization_years": AMORT_YEARS,
        "dscr": NOI / BASE_DEBT_SERVICE,
    }
    base.update(overrides)
    return base


def _a11_baseline(**overrides):
    base = {
        "stabilized_noi": 400_000, "return_on_cost": 0.075, "exit_cap_rate": 0.06,
    }
    base.update(overrides)
    return base


def test_no_stress_leaves_acquisition_asset_unchanged():
    baseline = _a02_baseline()
    result = stress_acquisition_asset(baseline=baseline, params=StressParams())
    assert result["stressed_noi"] == pytest.approx(baseline["noi"])
    assert result["stressed_dscr"] == pytest.approx(baseline["dscr"])
    assert result["value_change_pct"] == pytest.approx(0.0)
    assert not result["dscr_breach"]


def test_vacancy_shock_lowers_noi_and_dscr():
    baseline = _a02_baseline()
    result = stress_acquisition_asset(baseline=baseline, params=StressParams(vacancy_shock_bps=200))
    assert result["stressed_noi"] < baseline["noi"]
    assert result["stressed_dscr"] < baseline["dscr"]


def test_rate_shock_lowers_dscr_without_changing_noi():
    baseline = _a02_baseline()
    result = stress_acquisition_asset(baseline=baseline, params=StressParams(interest_rate_shock_bps=100))
    assert result["stressed_noi"] == pytest.approx(baseline["noi"])
    assert result["stressed_dscr"] < baseline["dscr"]


def test_cap_rate_expansion_reduces_value():
    baseline = _a02_baseline()
    result = stress_acquisition_asset(baseline=baseline, params=StressParams(cap_rate_expansion_bps=100))
    assert result["stressed_value"] < result["original_value"]
    assert result["value_change_pct"] < 0


def test_severe_combined_stress_can_breach_dscr():
    baseline = _a02_baseline()
    result = stress_acquisition_asset(
        baseline=baseline,
        params=StressParams(interest_rate_shock_bps=300, vacancy_shock_bps=1500, cap_rate_expansion_bps=150),
    )
    assert result["dscr_breach"]
    assert result["stressed_dscr"] < 1.00


def test_development_asset_has_no_dscr_but_stresses_value():
    baseline = _a11_baseline()
    result = stress_development_asset(baseline=baseline, params=StressParams(cap_rate_expansion_bps=100))
    assert result["stressed_dscr"] is None
    assert not result["dscr_breach"]
    assert result["stressed_value"] < result["original_value"]
    assert result["stressed_development_spread"] < baseline["return_on_cost"] - baseline["exit_cap_rate"]


def test_summarize_portfolio_flags_dscr_breaches_and_most_exposed():
    healthy = stress_acquisition_asset(baseline=_a02_baseline(), params=StressParams(vacancy_shock_bps=100))
    healthy["deal_id"] = "healthy-deal"
    healthy["property_address"] = "Healthy Deal"

    breached = stress_acquisition_asset(
        baseline=_a02_baseline(),
        params=StressParams(interest_rate_shock_bps=300, vacancy_shock_bps=1500, cap_rate_expansion_bps=150),
    )
    breached["deal_id"] = "breached-deal"
    breached["property_address"] = "Breached Deal"

    summary = summarize_portfolio_stress([healthy, breached])
    assert summary["asset_count"] == 2
    assert "breached-deal" in summary["assets_with_dscr_breach"]
    assert "healthy-deal" not in summary["assets_with_dscr_breach"]
    assert summary["most_exposed_assets"][0]["deal_id"] == "breached-deal"
