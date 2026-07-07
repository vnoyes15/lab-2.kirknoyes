"""Deal Scenario Modeling — Section 63.

"Scenario modeling lets operators define a named set of assumption changes and see the
combined impact simultaneously... 'Bear case: rents 8% below pro forma + construction
costs 12% over budget + exit cap rate up 50bps' produces a complete financial output.
Operators can hold two or three named scenarios side by side."

Distinct from A-02/A-11's sensitivity tables (arx/validation/acquisition_validation.py,
arx/validation/development_validation.py), which vary exactly one axis at a time to
prove directional consistency (MV5/DV5). A scenario applies several overrides at once
against the deal's active snapshot as a baseline. Pure deterministic recompute, no AI —
same contract as arx/agents/momentum_scoring.py: this isn't a 14th agent, it's Python
arithmetic over numbers the active A-02/A-11 snapshot already produced.
"""
from dataclasses import dataclass

from arx.agents.loan_math import compute_annual_debt_service


@dataclass(frozen=True)
class AcquisitionScenarioOverrides:
    rent_change_pct: float = 0.0
    vacancy_rate_override: float | None = None
    expense_change_pct: float = 0.0
    interest_rate_override: float | None = None


@dataclass(frozen=True)
class DevelopmentScenarioOverrides:
    construction_cost_overrun_pct: float = 0.0
    rent_change_pct: float = 0.0
    exit_cap_rate_override: float | None = None


def run_acquisition_scenario(*, baseline: dict, overrides: AcquisitionScenarioOverrides) -> dict:
    """baseline is the active A-02 snapshot's output_payload (Section 87 A02Output),
    which already carries purchase_price/loan_amount/ltv/interest_rate/
    amortization_years alongside the underwriting numbers. Recomputes NOI, cap rate,
    DSCR, and cash-on-cash under the combined overrides."""
    gross_rent = baseline["gross_rent"] * (1 + overrides.rent_change_pct)
    vacancy_rate = (
        overrides.vacancy_rate_override if overrides.vacancy_rate_override is not None
        else baseline["vacancy_rate"]
    )
    operating_expenses_total = sum(baseline["operating_expenses"].values()) * (1 + overrides.expense_change_pct)
    noi = gross_rent * (1 - vacancy_rate) - operating_expenses_total
    cap_rate = noi / baseline["purchase_price"]

    interest_rate = (
        overrides.interest_rate_override if overrides.interest_rate_override is not None
        else baseline["interest_rate"]
    )
    annual_debt_service = compute_annual_debt_service(
        baseline["loan_amount"], interest_rate, baseline["amortization_years"],
    )
    dscr = noi / annual_debt_service
    cash_on_cash = (noi - annual_debt_service) / (baseline["purchase_price"] * (1 - baseline["ltv"]))

    return {
        "gross_rent": gross_rent, "vacancy_rate": vacancy_rate,
        "operating_expenses_total": operating_expenses_total, "noi": noi, "cap_rate": cap_rate,
        "dscr": dscr, "cash_on_cash": cash_on_cash, "dscr_hard_fail": dscr < 1.00,
    }


def run_development_scenario(
    *, baseline: dict, overrides: DevelopmentScenarioOverrides,
) -> dict:
    """baseline is the active A-11 snapshot's output_payload (Section 87 A11Output).
    "construction costs N% over budget" is applied to hard_costs specifically (the
    literal construction line item) — soft/financing/land costs and contingency are
    unaffected by a construction cost overrun. "rents N% below pro forma" scales
    stabilized_noi directly, an approximation (NOI isn't 100% rent-driven) documented
    here rather than silently presented as exact."""
    cost_breakdown = baseline["cost_breakdown"]
    hard_costs = cost_breakdown["hard_costs"] * (1 + overrides.construction_cost_overrun_pct)
    total_project_cost = (
        cost_breakdown["land_cost"] + hard_costs + cost_breakdown["soft_costs"]
        + cost_breakdown["financing_costs"] + cost_breakdown["contingency"]
    )
    stabilized_noi = baseline["stabilized_noi"] * (1 + overrides.rent_change_pct)
    return_on_cost = stabilized_noi / total_project_cost
    exit_cap_rate = (
        overrides.exit_cap_rate_override if overrides.exit_cap_rate_override is not None
        else baseline["exit_cap_rate"]
    )
    development_spread = return_on_cost - exit_cap_rate

    return {
        "total_project_cost": total_project_cost, "stabilized_noi": stabilized_noi,
        "return_on_cost": return_on_cost, "exit_cap_rate": exit_cap_rate,
        "development_spread": development_spread, "value_destructive": development_spread < 0,
    }
