"""Development validation suite (A-11) — Section 15, checks DV1-DV5.

Same pure-Python, no-AI contract as arx/validation/acquisition_validation.py.
"""
from arx.validation.acquisition_validation import check_sensitivity_directional
from arx.validation.results import CheckResult, ValidationSuiteResult
from arx.validation.tolerance import approx_equal as _approx_equal

# Section 15: "Tolerance ±0.1%" for DV1, "±0.5%" for DV3.
ROC_TOLERANCE = 0.001
TOTAL_COST_TOLERANCE = 0.005

# DV4: how closely a reported IRR must match the IRR implied by the reported cash flows.
IRR_TOLERANCE = 0.001


def check_return_on_cost_consistency(
    stabilized_noi: float, total_project_cost: float, reported_roc: float
) -> CheckResult:
    """DV1: reported_roc ≈ stabilized_noi ÷ total_project_cost."""
    if total_project_cost <= 0:
        return CheckResult("DV1", False, "total_project_cost must be > 0 to compute return on cost")
    expected = stabilized_noi / total_project_cost
    passed = _approx_equal(expected, reported_roc, ROC_TOLERANCE)
    return CheckResult(
        "DV1", passed,
        "Return on cost consistent with stabilized NOI / total project cost" if passed
        else f"Reported ROC {reported_roc} does not match computed {expected:.6f}",
        expected=expected, actual=reported_roc,
    )


def check_development_spread(
    return_on_cost: float, exit_cap_rate: float, reported_spread: float, value_destructive_flag: bool
) -> CheckResult:
    """DV2: reported_spread ≈ return_on_cost − exit_cap_rate. Negative spread must be
    flagged as value-destructive — never silently reported as a plain number."""
    expected = return_on_cost - exit_cap_rate
    spread_consistent = _approx_equal(expected, reported_spread, ROC_TOLERANCE) if expected != 0 else (
        abs(reported_spread - expected) < 1e-6
    )
    flag_consistent = (expected < 0) == value_destructive_flag

    passed = spread_consistent and flag_consistent
    if not spread_consistent:
        message = f"Reported spread {reported_spread} does not match ROC - exit_cap_rate {expected:.6f}"
    elif not flag_consistent:
        message = f"Spread {expected:.6f} implies value_destructive={expected < 0}, but flag was {value_destructive_flag}"
    else:
        message = "Development spread and value-destructive flag both consistent"

    return CheckResult("DV2", passed, message, expected=expected, actual=reported_spread)


def check_total_project_cost(
    land_cost: float, hard_costs: float, soft_costs: float, financing_costs: float,
    contingency: float, reported_total_project_cost: float,
) -> CheckResult:
    """DV3: total_project_cost ≈ land_cost + hard_costs + soft_costs + financing_costs + contingency."""
    expected = land_cost + hard_costs + soft_costs + financing_costs + contingency
    passed = _approx_equal(expected, reported_total_project_cost, TOTAL_COST_TOLERANCE)
    return CheckResult(
        "DV3", passed,
        "Total project cost consistent with its cost breakdown" if passed
        else f"Reported total_project_cost {reported_total_project_cost} does not match sum of parts {expected:.6f}",
        expected=expected, actual=reported_total_project_cost,
    )


def _irr(cash_flows: list[float], guess: float = 0.1, tolerance: float = 1e-7, max_iterations: int = 200) -> float | None:
    """Newton's method IRR solver over a periodic cash flow series (cash_flows[0] is the
    initial outlay, typically negative). Returns None if it fails to converge — pure
    Python, no numpy/numpy-financial dependency for a single-purpose deterministic check.
    """
    rate = guess
    for _ in range(max_iterations):
        npv = sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows))
        d_npv = sum(-t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cash_flows))
        if d_npv == 0:
            return None
        new_rate = rate - npv / d_npv
        if abs(new_rate - rate) < tolerance:
            return new_rate
        rate = new_rate
    return None


def check_irr_consistency(cash_flows: list[float], reported_irr: float) -> CheckResult:
    """DV4: IRR must be consistent with modeled cash flows over the hold period.
    cash_flows[0] is the initial equity outlay (negative); subsequent entries are
    periodic distributions, with the final entry including any disposition/refi proceeds.
    """
    computed = _irr(cash_flows)
    if computed is None:
        return CheckResult("DV4", False, "IRR solver did not converge on the reported cash flow series")
    passed = _approx_equal(computed, reported_irr, IRR_TOLERANCE) if computed != 0 else abs(reported_irr) < 1e-6
    return CheckResult(
        "DV4", passed,
        "Reported IRR consistent with modeled cash flows" if passed
        else f"Reported IRR {reported_irr} does not match cash-flow-implied IRR {computed:.6f}",
        expected=computed, actual=reported_irr,
    )


def validate_development_output(output: dict) -> ValidationSuiteResult:
    """Runs the full development suite (DV1-DV5) against an A-11-shaped output dict.

    Expected keys: stabilized_noi, total_project_cost, return_on_cost, exit_cap_rate,
    development_spread, value_destructive, cost_breakdown (dict with land_cost,
    hard_costs, soft_costs, financing_costs, contingency), cash_flows, irr, and
    optionally sensitivity_table + sensitivity_scenario_order to also run DV5.
    """
    cost_breakdown = output["cost_breakdown"]
    results = [
        check_return_on_cost_consistency(output["stabilized_noi"], output["total_project_cost"], output["return_on_cost"]),
        check_development_spread(
            output["return_on_cost"], output["exit_cap_rate"], output["development_spread"], output["value_destructive"]
        ),
        check_total_project_cost(
            cost_breakdown["land_cost"], cost_breakdown["hard_costs"], cost_breakdown["soft_costs"],
            cost_breakdown["financing_costs"], cost_breakdown["contingency"], output["total_project_cost"],
        ),
        check_irr_consistency(output["cash_flows"], output["irr"]),
    ]

    if "sensitivity_table" in output and "sensitivity_scenario_order" in output:
        results.append(
            check_sensitivity_directional(
                output["sensitivity_table"], "return_on_cost", output["sensitivity_scenario_order"]
            )
        )

    return ValidationSuiteResult(results)
