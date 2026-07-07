import pytest

from arx.agents.equity_waterfall import (
    CoGpSplit,
    SplitRatio,
    apply_co_gp_split,
    apply_ground_lease,
    apply_mezzanine_layer,
    preferred_equity_waterfall,
    simple_lp_gp_waterfall,
)


def test_split_ratio_rejects_percentages_not_summing_to_one():
    with pytest.raises(ValueError):
        SplitRatio(lp_pct=0.8, gp_pct=0.3)


def test_simple_waterfall_conserves_total_distribution():
    result = simple_lp_gp_waterfall(
        lp_capital=800_000, gp_capital=200_000, total_distributable_proceeds=2_000_000,
        hurdle_moic=1.5, base_split=SplitRatio(0.8, 0.2), promote_split=SplitRatio(0.7, 0.3),
    )
    assert result.lp_total_distribution + result.gp_total_distribution == pytest.approx(2_000_000)


def test_simple_waterfall_promote_shifts_split_above_hurdle():
    result = simple_lp_gp_waterfall(
        lp_capital=800_000, gp_capital=200_000, total_distributable_proceeds=2_000_000,
        hurdle_moic=1.5, base_split=SplitRatio(0.8, 0.2), promote_split=SplitRatio(0.7, 0.3),
    )
    base_tier = next(t for t in result.tiers if t.tier == "base_split")
    promote_tier = next(t for t in result.tiers if t.tier == "promote_split")
    assert base_tier.lp_amount == pytest.approx(400_000)
    assert base_tier.gp_amount == pytest.approx(100_000)
    assert promote_tier.lp_amount == pytest.approx(350_000)
    assert promote_tier.gp_amount == pytest.approx(150_000)
    assert result.lp_moic == pytest.approx(1.9375)
    assert result.gp_moic == pytest.approx(2.25)


def test_simple_waterfall_below_hurdle_never_reaches_promote():
    result = simple_lp_gp_waterfall(
        lp_capital=800_000, gp_capital=200_000, total_distributable_proceeds=1_100_000,
        hurdle_moic=1.5, base_split=SplitRatio(0.8, 0.2), promote_split=SplitRatio(0.7, 0.3),
    )
    promote_tier = next(t for t in result.tiers if t.tier == "promote_split")
    assert promote_tier.lp_amount == pytest.approx(0.0)
    assert promote_tier.gp_amount == pytest.approx(0.0)


def test_simple_waterfall_proceeds_below_capital_returns_partial_pro_rata():
    result = simple_lp_gp_waterfall(
        lp_capital=800_000, gp_capital=200_000, total_distributable_proceeds=500_000,
        hurdle_moic=1.5, base_split=SplitRatio(0.8, 0.2), promote_split=SplitRatio(0.7, 0.3),
    )
    roc_tier = next(t for t in result.tiers if t.tier == "return_of_capital")
    assert roc_tier.lp_amount == pytest.approx(400_000)  # 80% of the 500k pro rata
    assert roc_tier.gp_amount == pytest.approx(100_000)
    assert result.lp_total_distribution == pytest.approx(400_000)
    assert result.gp_total_distribution == pytest.approx(100_000)


def test_preferred_equity_waterfall_conserves_total_and_catchup_ratio():
    result = preferred_equity_waterfall(
        lp_capital=800_000, gp_capital=200_000, total_distributable_proceeds=1_500_000,
        pref_rate=0.08, hold_period_years=5, catch_up_pct=0.20, residual_split=SplitRatio(0.8, 0.2),
    )
    assert result.lp_total_distribution + result.gp_total_distribution == pytest.approx(1_500_000)

    pref_tier = next(t for t in result.tiers if t.tier == "preferred_return")
    catchup_tier = next(t for t in result.tiers if t.tier == "gp_catch_up")
    # GP's catch-up should bring its share of profit distributed-so-far to exactly
    # catch_up_pct (the defining property of a catch-up tier).
    profit_so_far = pref_tier.lp_amount + catchup_tier.gp_amount
    assert catchup_tier.gp_amount / profit_so_far == pytest.approx(0.20)


def test_preferred_equity_waterfall_insufficient_proceeds_for_full_pref():
    result = preferred_equity_waterfall(
        lp_capital=800_000, gp_capital=200_000, total_distributable_proceeds=1_050_000,
        pref_rate=0.08, hold_period_years=5, catch_up_pct=0.20, residual_split=SplitRatio(0.8, 0.2),
    )
    pref_tier = next(t for t in result.tiers if t.tier == "preferred_return")
    catchup_tier = next(t for t in result.tiers if t.tier == "gp_catch_up")
    residual_tier = next(t for t in result.tiers if t.tier == "residual_split")
    assert pref_tier.lp_amount == pytest.approx(50_000)  # only 50k left after 1M return of capital
    assert catchup_tier.gp_amount == pytest.approx(0.0)
    assert residual_tier.lp_amount == pytest.approx(0.0) and residual_tier.gp_amount == pytest.approx(0.0)


def test_co_gp_split_divides_gp_profit_by_share():
    split = CoGpSplit(shares={"ZONIQ": 0.6, "Co-GP Partner": 0.4})
    result = apply_co_gp_split(gp_total_distribution=100_000, split=split)
    assert result["ZONIQ"] == pytest.approx(60_000)
    assert result["Co-GP Partner"] == pytest.approx(40_000)


def test_co_gp_split_rejects_shares_not_summing_to_one():
    with pytest.raises(ValueError):
        CoGpSplit(shares={"ZONIQ": 0.5, "Co-GP Partner": 0.4})


def test_mezzanine_layer_reduces_equity_distributable():
    equity_distributable, mezz_paid = apply_mezzanine_layer(
        total_distributable_proceeds=2_000_000, mezz_principal=500_000, mezz_rate=0.10, mezz_term_years=3,
    )
    expected_mezz = 500_000 * (1.10 ** 3)
    assert mezz_paid == pytest.approx(expected_mezz)
    assert equity_distributable == pytest.approx(2_000_000 - expected_mezz)


def test_mezzanine_layer_caps_at_available_proceeds():
    equity_distributable, mezz_paid = apply_mezzanine_layer(
        total_distributable_proceeds=400_000, mezz_principal=500_000, mezz_rate=0.10, mezz_term_years=3,
    )
    assert mezz_paid == pytest.approx(400_000)
    assert equity_distributable == pytest.approx(0.0)


def test_ground_lease_reduces_leasehold_distributable():
    leasehold_distributable, ground_rent_paid = apply_ground_lease(
        total_distributable_proceeds=2_000_000, ground_rent_annual=50_000, lease_term_years=10,
    )
    assert ground_rent_paid == pytest.approx(500_000)
    assert leasehold_distributable == pytest.approx(1_500_000)
