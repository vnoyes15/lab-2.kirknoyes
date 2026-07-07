"""Acquisition validation suite (A-02) — Section 15, checks MV1-MV6.

Pure, deterministic Python. No AI involved (Section 05 tech stack: "Math validation:
Python native"). Every function takes plain numbers/dicts and returns a CheckResult —
no dependency on the agent, the database, or FastAPI, so this module can be unit tested
in complete isolation and reused unchanged by A-02 once it lands in Phase 2.
"""
from arx.validation.results import CheckResult, ValidationSuiteResult
from arx.validation.tolerance import approx_equal

# Section 15: "Tolerance ±0.1%" for MV1-MV3. Interpreted as relative tolerance against
# the reported value (0.001 = 0.1%).
RELATIVE_TOLERANCE = 0.001


def _approx_equal(expected: float, actual: float, rel_tol: float = RELATIVE_TOLERANCE) -> bool:
    return approx_equal(expected, actual, rel_tol)


def check_cap_rate_consistency(noi: float, purchase_price: float, reported_cap_rate: float) -> CheckResult:
    """MV1: reported_cap_rate ≈ noi ÷ purchase_price."""
    if purchase_price <= 0:
        return CheckResult("MV1", False, "purchase_price must be > 0 to compute cap rate")
    expected = noi / purchase_price
    passed = _approx_equal(expected, reported_cap_rate)
    return CheckResult(
        "MV1", passed,
        "Cap rate consistent with NOI / purchase price" if passed
        else f"Reported cap rate {reported_cap_rate} does not match NOI/price {expected:.6f}",
        expected=expected, actual=reported_cap_rate,
    )


def check_dscr_consistency(noi: float, annual_debt_service: float, reported_dscr: float) -> CheckResult:
    """MV2: reported_dscr ≈ noi ÷ annual_debt_service."""
    if annual_debt_service <= 0:
        return CheckResult("MV2", False, "annual_debt_service must be > 0 to compute DSCR")
    expected = noi / annual_debt_service
    passed = _approx_equal(expected, reported_dscr)
    return CheckResult(
        "MV2", passed,
        "DSCR consistent with NOI / annual debt service" if passed
        else f"Reported DSCR {reported_dscr} does not match NOI/debt_service {expected:.6f}",
        expected=expected, actual=reported_dscr,
    )


def check_cash_on_cash_consistency(
    noi: float, debt_service: float, purchase_price: float, ltv: float, reported_coc: float
) -> CheckResult:
    """MV3: reported_coc ≈ (NOI − debt_service) ÷ (purchase_price × (1−LTV))."""
    equity = purchase_price * (1 - ltv)
    if equity <= 0:
        return CheckResult("MV3", False, "Implied equity (purchase_price * (1-LTV)) must be > 0")
    expected = (noi - debt_service) / equity
    passed = _approx_equal(expected, reported_coc)
    return CheckResult(
        "MV3", passed,
        "Cash-on-cash consistent with (NOI - debt_service) / equity" if passed
        else f"Reported CoC {reported_coc} does not match computed {expected:.6f}",
        expected=expected, actual=reported_coc,
    )


def check_noi_construction(
    gross_rent: float, vacancy_rate: float, operating_expenses: dict[str, float], reported_noi: float
) -> CheckResult:
    """MV4: reported_noi ≈ gross_rent × (1−vacancy) − sum(operating_expenses)."""
    expected = gross_rent * (1 - vacancy_rate) - sum(operating_expenses.values())
    passed = _approx_equal(expected, reported_noi)
    return CheckResult(
        "MV4", passed,
        "NOI consistent with gross_rent x (1-vacancy) - operating_expenses" if passed
        else f"Reported NOI {reported_noi} does not match computed {expected:.6f}",
        expected=expected, actual=reported_noi,
    )


def check_sensitivity_directional(
    scenarios: dict[str, dict[str, float]],
    metric: str,
    worse_to_better_order: list[str],
) -> CheckResult:
    """MV5: worse inputs must produce worse (or equal) returns in every scenario.

    scenarios: {scenario_label: {metric_name: value, ...}, ...} — e.g. the
    A-02 sensitivity_table (Section 87), keyed by scenario label.
    worse_to_better_order: scenario labels ordered from worst-case input assumption to
    best-case, e.g. ["rent_-10pct", "rent_-5pct", "base", "rent_+5pct", "rent_+10pct"].
    """
    missing = [label for label in worse_to_better_order if label not in scenarios]
    if missing:
        return CheckResult("MV5", False, f"Sensitivity table missing scenarios: {missing}")

    values = [scenarios[label][metric] for label in worse_to_better_order]
    for i in range(len(values) - 1):
        if values[i] > values[i + 1] + 1e-9:
            return CheckResult(
                "MV5", False,
                f"Non-monotonic sensitivity: {worse_to_better_order[i]}={values[i]} > "
                f"{worse_to_better_order[i + 1]}={values[i + 1]} for metric '{metric}'",
            )
    return CheckResult("MV5", True, f"Sensitivity table is monotonic for metric '{metric}'")


def check_dscr_hard_fail_flag(dscr: float, reported_dscr_hard_fail: bool) -> CheckResult:
    """MV6: DSCR below 1.00 = hard-fail flag regardless of other metrics. Cross-checks
    that the agent's own reported flag agrees with the DSCR it just reported — an agent
    cannot silently under-report the hard-fail condition."""
    expected = dscr < 1.00
    passed = expected == reported_dscr_hard_fail
    return CheckResult(
        "MV6", passed,
        "dscr_hard_fail flag consistent with DSCR" if passed
        else f"DSCR={dscr} implies dscr_hard_fail={expected}, but agent reported {reported_dscr_hard_fail}",
        expected=float(expected), actual=float(reported_dscr_hard_fail),
    )


def validate_acquisition_output(output: dict) -> ValidationSuiteResult:
    """Runs the full acquisition suite (MV1-MV6) against an A-02-shaped output dict.

    Expected keys: noi, purchase_price, cap_rate, annual_debt_service, dscr,
    debt_service, ltv, cash_on_cash, gross_rent, vacancy_rate, operating_expenses
    (dict), dscr_hard_fail, and optionally sensitivity_table + sensitivity_scenario_order
    to also run MV5.
    """
    results = [
        check_cap_rate_consistency(output["noi"], output["purchase_price"], output["cap_rate"]),
        check_dscr_consistency(output["noi"], output["annual_debt_service"], output["dscr"]),
        check_cash_on_cash_consistency(
            output["noi"], output["debt_service"], output["purchase_price"], output["ltv"], output["cash_on_cash"]
        ),
        check_noi_construction(
            output["gross_rent"], output["vacancy_rate"], output["operating_expenses"], output["noi"]
        ),
        check_dscr_hard_fail_flag(output["dscr"], output["dscr_hard_fail"]),
    ]

    if "sensitivity_table" in output and "sensitivity_scenario_order" in output:
        results.append(
            check_sensitivity_directional(
                output["sensitivity_table"], "cap_rate", output["sensitivity_scenario_order"]
            )
        )

    return ValidationSuiteResult(results)
