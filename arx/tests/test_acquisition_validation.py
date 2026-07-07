from arx.validation.acquisition_validation import (
    check_cap_rate_consistency,
    check_cash_on_cash_consistency,
    check_dscr_consistency,
    check_dscr_hard_fail_flag,
    check_noi_construction,
    check_sensitivity_directional,
    validate_acquisition_output,
)


def test_cap_rate_consistency_pass():
    # NOI 300,000 / price 5,000,000 = 6.0% cap rate.
    result = check_cap_rate_consistency(noi=300_000, purchase_price=5_000_000, reported_cap_rate=0.06)
    assert result.passed


def test_cap_rate_consistency_fail():
    result = check_cap_rate_consistency(noi=300_000, purchase_price=5_000_000, reported_cap_rate=0.08)
    assert not result.passed
    assert result.check_id == "MV1"


def test_dscr_consistency():
    assert check_dscr_consistency(noi=300_000, annual_debt_service=250_000, reported_dscr=1.2).passed
    assert not check_dscr_consistency(noi=300_000, annual_debt_service=250_000, reported_dscr=2.0).passed


def test_cash_on_cash_consistency():
    # equity = 5,000,000 * (1 - 0.75) = 1,250,000. (NOI 300,000 - debt_service 250,000) / 1,250,000 = 0.04
    result = check_cash_on_cash_consistency(
        noi=300_000, debt_service=250_000, purchase_price=5_000_000, ltv=0.75, reported_coc=0.04
    )
    assert result.passed


def test_noi_construction():
    # gross_rent 500,000 * (1 - 0.07) = 465,000; minus 165,000 opex = 300,000 NOI.
    result = check_noi_construction(
        gross_rent=500_000,
        vacancy_rate=0.07,
        operating_expenses={"management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
                             "insurance": 25_000, "taxes": 40_000, "other": 10_000},
        reported_noi=300_000,
    )
    assert result.passed


def test_dscr_hard_fail_flag_below_one():
    result = check_dscr_hard_fail_flag(dscr=0.95, reported_dscr_hard_fail=True)
    assert result.passed


def test_dscr_hard_fail_flag_mismatch_is_caught():
    # DSCR below 1.0 but agent didn't flag it — this is exactly the failure MV6 exists
    # to catch (Section 15: "DSCR below 1.00 = hard-fail flag regardless of other metrics").
    result = check_dscr_hard_fail_flag(dscr=0.95, reported_dscr_hard_fail=False)
    assert not result.passed


def test_sensitivity_directional_monotonic_passes():
    scenarios = {
        "rent_-10pct": {"cap_rate": 0.050},
        "rent_-5pct": {"cap_rate": 0.055},
        "base": {"cap_rate": 0.060},
        "rent_+5pct": {"cap_rate": 0.065},
        "rent_+10pct": {"cap_rate": 0.070},
    }
    order = ["rent_-10pct", "rent_-5pct", "base", "rent_+5pct", "rent_+10pct"]
    assert check_sensitivity_directional(scenarios, "cap_rate", order).passed


def test_sensitivity_directional_non_monotonic_fails():
    scenarios = {
        "rent_-10pct": {"cap_rate": 0.070},  # worse rent assumption showing a better cap rate — wrong direction
        "base": {"cap_rate": 0.060},
    }
    result = check_sensitivity_directional(scenarios, "cap_rate", ["rent_-10pct", "base"])
    assert not result.passed
    assert result.check_id == "MV5"


def test_validate_acquisition_output_all_consistent():
    output = {
        "noi": 300_000,
        "purchase_price": 5_000_000,
        "cap_rate": 0.06,
        "annual_debt_service": 250_000,
        "dscr": 1.2,
        "debt_service": 250_000,
        "ltv": 0.75,
        "cash_on_cash": 0.04,
        "gross_rent": 500_000,
        "vacancy_rate": 0.07,
        "operating_expenses": {"management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
                                "insurance": 25_000, "taxes": 40_000, "other": 10_000},
        "dscr_hard_fail": False,
    }
    suite = validate_acquisition_output(output)
    assert suite.passed, suite.to_dict()


def test_validate_acquisition_output_catches_inconsistent_noi():
    output = {
        "noi": 999_999,  # inconsistent with gross_rent/vacancy/opex below
        "purchase_price": 5_000_000,
        "cap_rate": 999_999 / 5_000_000,
        "annual_debt_service": 250_000,
        "dscr": 999_999 / 250_000,
        "debt_service": 250_000,
        "ltv": 0.75,
        "cash_on_cash": (999_999 - 250_000) / 1_250_000,
        "gross_rent": 500_000,
        "vacancy_rate": 0.07,
        "operating_expenses": {"management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
                                "insurance": 25_000, "taxes": 40_000, "other": 10_000},
        "dscr_hard_fail": False,
    }
    suite = validate_acquisition_output(output)
    assert not suite.passed
    failed_ids = {r.check_id for r in suite.failed_checks}
    assert "MV4" in failed_ids
