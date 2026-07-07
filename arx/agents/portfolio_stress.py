"""Portfolio Stress Test — Section 47.

"POST /api/v1/portfolio/stress-test with scenario parameters (interest rates +100bps,
vacancy +200bps, cap rate expansion, or combined). Returns per-asset DSCR,
portfolio-level NOI impact, assets most exposed... Development assets in construction
phase use different stress parameters from stabilized assets."

Pure deterministic recompute over each owned asset's active underwriting snapshot —
same contract as arx/agents/scenario_modeling.py: not a 14th agent, just arithmetic.

Acquisition/stabilized assets (active A-02 snapshot) get the full three-lever stress:
vacancy shock reduces NOI, rate shock raises debt service (both feed a stressed DSCR),
cap rate expansion compresses implied value. Development assets still in construction
(active A-11 snapshot, not yet stabilized/closed/dead) have no loan_amount/
interest_rate in their output schema — A-11 models construction financing risk through
its own cost_overrun/absorption_delay sensitivity tables (Section 87), not a DSCR — so
DSCR is reported as None for them rather than fabricated, and only the cap rate
expansion lever (applied to exit_cap_rate, impacting implied value / return spread)
applies. That's the "different stress parameters" the spec calls for.
"""
from dataclasses import dataclass

from arx.agents.loan_math import compute_annual_debt_service


@dataclass(frozen=True)
class StressParams:
    interest_rate_shock_bps: float = 0.0
    vacancy_shock_bps: float = 0.0
    cap_rate_expansion_bps: float = 0.0


def stress_acquisition_asset(*, baseline: dict, params: StressParams) -> dict:
    """baseline is an active A-02 snapshot's output_payload (Section 87 A02Output)."""
    vacancy_rate = min(1.0, baseline["vacancy_rate"] + params.vacancy_shock_bps / 10_000)
    operating_expenses_total = sum(baseline["operating_expenses"].values())
    noi = baseline["gross_rent"] * (1 - vacancy_rate) - operating_expenses_total

    interest_rate = baseline["interest_rate"] + params.interest_rate_shock_bps / 10_000
    annual_debt_service = compute_annual_debt_service(
        baseline["loan_amount"], interest_rate, baseline["amortization_years"],
    )
    dscr = noi / annual_debt_service

    cap_rate = baseline["cap_rate"] + params.cap_rate_expansion_bps / 10_000
    original_value = baseline["noi"] / baseline["cap_rate"]
    stressed_value = noi / cap_rate
    value_change_pct = (stressed_value - original_value) / original_value

    return {
        "asset_type": "acquisition",
        "original_noi": baseline["noi"], "stressed_noi": noi,
        "noi_change": noi - baseline["noi"],
        "original_dscr": baseline["dscr"], "stressed_dscr": dscr,
        "dscr_breach": dscr < 1.00,
        "original_value": original_value, "stressed_value": stressed_value,
        "value_change_pct": value_change_pct,
    }


def stress_development_asset(*, baseline: dict, params: StressParams) -> dict:
    """baseline is an active A-11 snapshot's output_payload (Section 87 A11Output)."""
    exit_cap_rate = baseline["exit_cap_rate"] + params.cap_rate_expansion_bps / 10_000
    original_value = baseline["stabilized_noi"] / baseline["exit_cap_rate"]
    stressed_value = baseline["stabilized_noi"] / exit_cap_rate
    value_change_pct = (stressed_value - original_value) / original_value
    development_spread = baseline["return_on_cost"] - exit_cap_rate

    return {
        "asset_type": "development",
        "original_noi": baseline["stabilized_noi"], "stressed_noi": baseline["stabilized_noi"],
        "noi_change": 0.0,
        "original_dscr": None, "stressed_dscr": None, "dscr_breach": False,
        "original_value": original_value, "stressed_value": stressed_value,
        "value_change_pct": value_change_pct,
        "stressed_development_spread": development_spread,
    }


def summarize_portfolio_stress(assets: list[dict]) -> dict:
    """assets is a list of per-asset dicts (each already tagged with deal_id/
    property_address by the caller plus the stress_*_asset() output above). Portfolio
    NOI impact only sums assets where NOI actually moves under stress (acquisition
    assets) — development assets under construction contribute 0 by construction of
    stress_development_asset above, so summing all of them is still correct."""
    total_noi_impact = sum(a["noi_change"] for a in assets)
    most_exposed = sorted(assets, key=lambda a: a["value_change_pct"])[:5]
    return {
        "asset_count": len(assets),
        "portfolio_noi_impact": total_noi_impact,
        "assets_with_dscr_breach": [a["deal_id"] for a in assets if a["dscr_breach"]],
        "most_exposed_assets": most_exposed,
    }
