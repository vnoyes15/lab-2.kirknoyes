from datetime import date

import pytest

from arx.agents.loan_math import compute_annual_debt_service
from arx.agents.refi_disposition import (
    analyze_disposition,
    analyze_refi,
    compute_1031_windows,
)

PURCHASE_PRICE = 5_000_000
LOAN_AMOUNT, LTV, INTEREST_RATE, AMORT_YEARS = 3_750_000, 0.75, 0.065, 30
NOI = 300_000
ANNUAL_DEBT_SERVICE = compute_annual_debt_service(LOAN_AMOUNT, INTEREST_RATE, AMORT_YEARS)


def _a02_baseline(**overrides):
    base = {
        "purchase_price": PURCHASE_PRICE, "loan_amount": LOAN_AMOUNT, "ltv": LTV,
        "interest_rate": INTEREST_RATE, "amortization_years": AMORT_YEARS,
        "annual_debt_service": ANNUAL_DEBT_SERVICE, "noi": NOI, "cap_rate": NOI / PURCHASE_PRICE,
    }
    base.update(overrides)
    return base


def test_refi_at_lower_rate_triggers_opportunity():
    baseline = _a02_baseline()
    result = analyze_refi(baseline=baseline, proposed_interest_rate=INTEREST_RATE - 0.01)
    assert result.improvement_bps > 50
    assert result.triggers_refi_opportunity
    assert result.cash_on_cash_improvement > 0


def test_refi_at_marginally_lower_rate_does_not_trigger():
    baseline = _a02_baseline()
    result = analyze_refi(baseline=baseline, proposed_interest_rate=INTEREST_RATE - 0.0005)
    assert result.improvement_bps < 50
    assert not result.triggers_refi_opportunity


def test_refi_at_higher_rate_never_triggers():
    baseline = _a02_baseline()
    result = analyze_refi(baseline=baseline, proposed_interest_rate=INTEREST_RATE + 0.01)
    assert result.improvement_bps < 0
    assert not result.triggers_refi_opportunity
    assert result.cash_on_cash_improvement < 0


def test_disposition_cap_rate_compression_triggers_above_threshold():
    baseline = _a02_baseline()
    acquisition_cap_rate = baseline["cap_rate"]
    result = analyze_disposition(baseline=baseline, current_market_cap_rate=acquisition_cap_rate * 0.8)
    assert result.appreciation_pct > 0
    assert result.triggers_disposition_opportunity


def test_disposition_small_compression_below_threshold_does_not_trigger():
    baseline = _a02_baseline()
    acquisition_cap_rate = baseline["cap_rate"]
    result = analyze_disposition(baseline=baseline, current_market_cap_rate=acquisition_cap_rate * 0.98)
    assert not result.triggers_disposition_opportunity


def test_disposition_cap_rate_expansion_never_triggers():
    baseline = _a02_baseline()
    acquisition_cap_rate = baseline["cap_rate"]
    result = analyze_disposition(baseline=baseline, current_market_cap_rate=acquisition_cap_rate * 1.2)
    assert result.appreciation_pct < 0
    assert not result.triggers_disposition_opportunity


def test_1031_windows_are_45_and_180_days_out():
    windows = compute_1031_windows(date(2026, 7, 1))
    assert windows.identification_deadline == date(2026, 8, 15)
    assert windows.close_deadline == date(2026, 12, 28)
