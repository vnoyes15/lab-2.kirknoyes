"""Portfolio Context for Deal Evaluation — Section 69.

"When A-02 or A-11 runs, it queries the portfolio layer for current aggregate
metrics: total portfolio debt service, weighted average DSCR, geographic
concentration, asset type concentration, total equity deployed. Then calculates
post-acquisition portfolio metrics and flags: DSCR impact, concentration increase,
equity deployment impact."

"A deal below ZONIQ's target cap rate range may be portfolio-optimal because it
diversifies geography. A deal that looks great in isolation may tip aggregate DSCR
below a covenant threshold. A-02 surfaces both."

Pure deterministic functions, no AI, no DB — same contract as portfolio_stress.py:
not a new agent, just arithmetic over the portfolio layer's existing owned-asset data
plus the candidate deal's own A-02/A-11 output. "Value" for concentration purposes is
purchase_price for acquisition assets and total_project_cost for development assets —
the two schemas don't share a loan_amount/dscr field, so debt-service/DSCR aggregates
only include assets that actually have one (acquisition), while geographic/asset-type
concentration covers every owned asset regardless of financing shape.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PortfolioAggregates:
    asset_count: int
    total_value: float
    total_loan_amount: float
    total_debt_service: float
    total_equity_deployed: float
    weighted_average_dscr: float | None
    geographic_concentration: dict[str, float] = field(default_factory=dict)  # submarket -> % of total_value
    asset_type_concentration: dict[str, float] = field(default_factory=dict)  # asset_type -> % of total_value


def compute_portfolio_aggregates(owned_assets: list[dict]) -> PortfolioAggregates:
    """Each entry in owned_assets is a dict with "value" and "asset_type" (every owned
    deal has these), plus "submarket", and — only for acquisition deals with an
    active A-02 snapshot — "loan_amount", "dscr", "annual_debt_service", "equity"."""
    total_value = sum(a["value"] for a in owned_assets)

    debt_bearing = [a for a in owned_assets if a.get("loan_amount") is not None]
    total_loan_amount = sum(a["loan_amount"] for a in debt_bearing)
    total_debt_service = sum(a["annual_debt_service"] for a in debt_bearing)
    total_equity_deployed = sum(a["equity"] for a in debt_bearing)
    weighted_average_dscr = (
        sum(a["dscr"] * a["loan_amount"] for a in debt_bearing) / total_loan_amount
        if total_loan_amount else None
    )

    geographic_concentration: dict[str, float] = {}
    asset_type_concentration: dict[str, float] = {}
    if total_value > 0:
        for asset in owned_assets:
            submarket = asset.get("submarket") or "unknown"
            geographic_concentration[submarket] = geographic_concentration.get(submarket, 0.0) + asset["value"]
            asset_type_concentration[asset["asset_type"]] = (
                asset_type_concentration.get(asset["asset_type"], 0.0) + asset["value"]
            )
        geographic_concentration = {k: v / total_value for k, v in geographic_concentration.items()}
        asset_type_concentration = {k: v / total_value for k, v in asset_type_concentration.items()}

    return PortfolioAggregates(
        asset_count=len(owned_assets), total_value=total_value, total_loan_amount=total_loan_amount,
        total_debt_service=total_debt_service, total_equity_deployed=total_equity_deployed,
        weighted_average_dscr=weighted_average_dscr,
        geographic_concentration=geographic_concentration, asset_type_concentration=asset_type_concentration,
    )


def compute_post_acquisition_impact(*, current: PortfolioAggregates, proposed: dict) -> dict:
    """proposed is the candidate deal's own values in the same shape as one
    owned_assets entry above (value, asset_type, submarket, and — for an acquisition
    deal — loan_amount/dscr/annual_debt_service/equity)."""
    new_total_value = current.total_value + proposed["value"]

    is_debt_bearing = proposed.get("loan_amount") is not None
    if is_debt_bearing:
        new_total_loan = current.total_loan_amount + proposed["loan_amount"]
        new_weighted_average_dscr = (
            (current.weighted_average_dscr or 0.0) * current.total_loan_amount
            + proposed["dscr"] * proposed["loan_amount"]
        ) / new_total_loan
        dscr_impact = (
            new_weighted_average_dscr - current.weighted_average_dscr
            if current.weighted_average_dscr is not None else None
        )
        new_equity_deployed = current.total_equity_deployed + proposed["equity"]
    else:
        new_weighted_average_dscr = current.weighted_average_dscr
        dscr_impact = None
        new_equity_deployed = current.total_equity_deployed

    submarket = proposed.get("submarket") or "unknown"
    asset_type = proposed["asset_type"]

    def _concentration_after(concentration_map: dict[str, float], key: str) -> float:
        prior_value = concentration_map.get(key, 0.0) * current.total_value
        return (prior_value + proposed["value"]) / new_total_value if new_total_value else 0.0

    return {
        "current_weighted_average_dscr": current.weighted_average_dscr,
        "post_acquisition_weighted_average_dscr": new_weighted_average_dscr,
        "dscr_impact": dscr_impact,
        "geographic_concentration_submarket": submarket,
        "geographic_concentration_before": current.geographic_concentration.get(submarket, 0.0),
        "geographic_concentration_after": _concentration_after(current.geographic_concentration, submarket),
        "asset_type": asset_type,
        "asset_type_concentration_before": current.asset_type_concentration.get(asset_type, 0.0),
        "asset_type_concentration_after": _concentration_after(current.asset_type_concentration, asset_type),
        "current_total_equity_deployed": current.total_equity_deployed,
        "post_acquisition_total_equity_deployed": new_equity_deployed,
        "equity_deployment_impact": new_equity_deployed - current.total_equity_deployed,
    }
