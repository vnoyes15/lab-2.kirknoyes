import pytest

from arx.agents.portfolio_context import compute_portfolio_aggregates, compute_post_acquisition_impact


def _acquisition_asset(**overrides):
    base = {
        "value": 5_000_000, "asset_type": "multifamily", "submarket": "Tacoma",
        "loan_amount": 3_750_000, "dscr": 1.30, "annual_debt_service": 284_000, "equity": 1_250_000,
    }
    base.update(overrides)
    return base


def test_empty_portfolio_has_no_dscr_and_zero_totals():
    aggregates = compute_portfolio_aggregates([])
    assert aggregates.asset_count == 0
    assert aggregates.weighted_average_dscr is None
    assert aggregates.total_value == 0


def test_aggregates_weight_dscr_by_loan_amount():
    assets = [
        _acquisition_asset(loan_amount=3_000_000, dscr=1.5),
        _acquisition_asset(loan_amount=1_000_000, dscr=1.0),
    ]
    aggregates = compute_portfolio_aggregates(assets)
    expected = (1.5 * 3_000_000 + 1.0 * 1_000_000) / 4_000_000
    assert aggregates.weighted_average_dscr == pytest.approx(expected)


def test_development_asset_without_loan_data_excluded_from_dscr():
    assets = [_acquisition_asset(), {"value": 8_000_000, "asset_type": "development", "submarket": "Seattle"}]
    aggregates = compute_portfolio_aggregates(assets)
    assert aggregates.weighted_average_dscr == pytest.approx(1.30)  # only the debt-bearing asset counts
    assert aggregates.total_value == 13_000_000


def test_geographic_and_asset_type_concentration_sum_to_one():
    assets = [
        _acquisition_asset(value=6_000_000, submarket="Tacoma", asset_type="multifamily"),
        _acquisition_asset(value=4_000_000, submarket="Seattle", asset_type="office"),
    ]
    aggregates = compute_portfolio_aggregates(assets)
    assert aggregates.geographic_concentration["Tacoma"] == pytest.approx(0.6)
    assert aggregates.geographic_concentration["Seattle"] == pytest.approx(0.4)
    assert sum(aggregates.asset_type_concentration.values()) == pytest.approx(1.0)


def test_post_acquisition_impact_reduces_concentration_when_diversifying():
    """Section 69's own example: a new deal in an underrepresented submarket should
    reduce that submarket's concentration share even though it adds value."""
    assets = [_acquisition_asset(value=9_000_000, submarket="Tacoma") for _ in range(1)]
    current = compute_portfolio_aggregates(assets)
    proposed = _acquisition_asset(
        value=1_000_000, submarket="Seattle", asset_type="office", loan_amount=750_000, dscr=1.4,
    )

    impact = compute_post_acquisition_impact(current=current, proposed=proposed)
    assert impact["geographic_concentration_submarket"] == "Seattle"
    assert impact["geographic_concentration_before"] == 0.0
    assert impact["geographic_concentration_after"] == pytest.approx(0.1)
    assert impact["asset_type_concentration_before"] == 0.0  # no office exposure before
    assert impact["asset_type_concentration_after"] == pytest.approx(0.1)  # office is now 10% of the portfolio


def test_post_acquisition_dscr_impact_can_be_negative():
    assets = [_acquisition_asset(loan_amount=5_000_000, dscr=1.5)]
    current = compute_portfolio_aggregates(assets)
    proposed = _acquisition_asset(loan_amount=1_000_000, dscr=1.05)

    impact = compute_post_acquisition_impact(current=current, proposed=proposed)
    assert impact["dscr_impact"] < 0
    assert impact["post_acquisition_weighted_average_dscr"] < impact["current_weighted_average_dscr"]


def test_development_proposal_has_no_dscr_impact():
    assets = [_acquisition_asset()]
    current = compute_portfolio_aggregates(assets)
    proposed = {"value": 8_000_000, "asset_type": "development", "submarket": "Seattle"}

    impact = compute_post_acquisition_impact(current=current, proposed=proposed)
    assert impact["dscr_impact"] is None
    assert impact["post_acquisition_weighted_average_dscr"] == current.weighted_average_dscr


def test_equity_deployment_impact_matches_proposed_equity():
    assets = [_acquisition_asset(equity=1_000_000)]
    current = compute_portfolio_aggregates(assets)
    proposed = _acquisition_asset(equity=500_000, loan_amount=2_000_000, dscr=1.2)

    impact = compute_post_acquisition_impact(current=current, proposed=proposed)
    assert impact["equity_deployment_impact"] == pytest.approx(500_000)
