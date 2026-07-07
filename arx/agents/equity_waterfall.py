"""JV & Complex Equity Structure Modeling — Section 70.

"Supported structures: Simple LP/GP with promote. Preferred equity with preferred
return and catch-up provisions. JV with co-GP profit sharing. Mezzanine debt layer.
Ground lease with residual ownership. Each structure has a defined input schema and
output format. Implementation scope: Phase 1 covers simple LP/GP waterfall and
preferred equity. Phase 6 adds full JV and complex structure modeling."

Nothing before Phase 6 actually implemented any waterfall math at all (A-13 Capital
Raise Intelligence only drafts investor-facing prose about a deal's capital stack) —
this module is the real foundation the spec says Phase 1 should have had, built now
alongside the Phase 6 structures the spec explicitly assigns here.

Pure deterministic functions, no AI, no DB — same contract as scenario_modeling.py and
portfolio_stress.py: not a 14th agent, just arithmetic.

Scope simplification, documented rather than silently assumed: every structure here
resolves against a single lump-sum total_distributable_proceeds figure (the caller's
cumulative operating cash flow plus exit/sale proceeds over the hold), not a
period-by-period cash flow timeline. A true multi-period waterfall needs to resolve
*when* the GP catch-up/promote tier is crossed across time (a goal-seek over the whole
cash flow series, since interim distributions and the final sale both feed it) — that
is materially more scope than this module takes on. Consequently the "hurdle" for the
simple LP/GP promote structure is expressed as a target multiple-on-invested-capital
(MOIC), a legitimate and commonly used alternative to an IRR hurdle, not a true
time-weighted IRR. Reported lp_moic/gp_moic are single-period multiples for the same
reason — not a time-weighted IRR.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SplitRatio:
    lp_pct: float
    gp_pct: float

    def __post_init__(self):
        if abs((self.lp_pct + self.gp_pct) - 1.0) > 1e-9:
            raise ValueError(f"lp_pct + gp_pct must equal 1.0, got {self.lp_pct + self.gp_pct}")


@dataclass(frozen=True)
class WaterfallTier:
    tier: str
    lp_amount: float
    gp_amount: float


@dataclass(frozen=True)
class WaterfallResult:
    tiers: list[WaterfallTier]
    lp_capital: float
    gp_capital: float
    lp_total_distribution: float
    gp_total_distribution: float
    lp_moic: float
    gp_moic: float

    def to_dict(self) -> dict:
        return {
            "tiers": [{"tier": t.tier, "lp_amount": t.lp_amount, "gp_amount": t.gp_amount} for t in self.tiers],
            "lp_capital": self.lp_capital, "gp_capital": self.gp_capital,
            "lp_total_distribution": self.lp_total_distribution, "gp_total_distribution": self.gp_total_distribution,
            "lp_moic": self.lp_moic, "gp_moic": self.gp_moic,
        }


def _return_of_capital(*, lp_capital: float, gp_capital: float, proceeds: float) -> tuple[WaterfallTier, float]:
    total_capital = lp_capital + gp_capital
    returned = min(proceeds, total_capital)
    lp_share = returned * (lp_capital / total_capital) if total_capital else 0.0
    gp_share = returned - lp_share
    return WaterfallTier("return_of_capital", lp_share, gp_share), proceeds - returned


def _finalize(*, lp_capital: float, gp_capital: float, tiers: list[WaterfallTier]) -> WaterfallResult:
    lp_total = sum(t.lp_amount for t in tiers)
    gp_total = sum(t.gp_amount for t in tiers)
    return WaterfallResult(
        tiers=tiers, lp_capital=lp_capital, gp_capital=gp_capital,
        lp_total_distribution=lp_total, gp_total_distribution=gp_total,
        lp_moic=lp_total / lp_capital if lp_capital else 0.0,
        gp_moic=gp_total / gp_capital if gp_capital else 0.0,
    )


def simple_lp_gp_waterfall(
    *, lp_capital: float, gp_capital: float, total_distributable_proceeds: float,
    hurdle_moic: float, base_split: SplitRatio, promote_split: SplitRatio,
) -> WaterfallResult:
    """"Simple LP/GP with promote": return of capital, then profit at base_split until
    LP's cumulative MOIC reaches hurdle_moic, then promote_split (GP's larger share)
    for the rest."""
    roc_tier, remaining = _return_of_capital(
        lp_capital=lp_capital, gp_capital=gp_capital, proceeds=total_distributable_proceeds,
    )
    total_profit = max(0.0, remaining)

    lp_profit_needed_for_hurdle = max(0.0, lp_capital * (hurdle_moic - 1))
    base_tier_pool = (
        min(total_profit, lp_profit_needed_for_hurdle / base_split.lp_pct)
        if base_split.lp_pct > 0 else 0.0
    )
    promote_tier_pool = total_profit - base_tier_pool

    base_tier = WaterfallTier(
        "base_split", base_tier_pool * base_split.lp_pct, base_tier_pool * base_split.gp_pct,
    )
    promote_tier = WaterfallTier(
        "promote_split", promote_tier_pool * promote_split.lp_pct, promote_tier_pool * promote_split.gp_pct,
    )
    return _finalize(lp_capital=lp_capital, gp_capital=gp_capital, tiers=[roc_tier, base_tier, promote_tier])


def preferred_equity_waterfall(
    *, lp_capital: float, gp_capital: float, total_distributable_proceeds: float,
    pref_rate: float, hold_period_years: float, catch_up_pct: float, residual_split: SplitRatio,
) -> WaterfallResult:
    """"Preferred equity with preferred return and catch-up provisions": return of
    capital, then LP's compounded preferred return, then a GP catch-up that brings
    GP's share of profit distributed so far up to catch_up_pct, then residual_split
    for whatever remains."""
    roc_tier, remaining = _return_of_capital(
        lp_capital=lp_capital, gp_capital=gp_capital, proceeds=total_distributable_proceeds,
    )

    lp_pref_accrued = lp_capital * ((1 + pref_rate) ** hold_period_years - 1)
    lp_pref_paid = min(remaining, lp_pref_accrued)
    pref_tier = WaterfallTier("preferred_return", lp_pref_paid, 0.0)
    remaining -= lp_pref_paid

    # GP catch-up: solve for gp_catchup such that gp_catchup / (lp_pref_paid + gp_catchup)
    # == catch_up_pct, i.e. GP's share of total profit distributed through this tier
    # reaches catch_up_pct.
    gp_catchup_target = (
        catch_up_pct * lp_pref_paid / (1 - catch_up_pct) if catch_up_pct < 1 else remaining
    )
    gp_catchup_paid = min(remaining, max(0.0, gp_catchup_target))
    catchup_tier = WaterfallTier("gp_catch_up", 0.0, gp_catchup_paid)
    remaining -= gp_catchup_paid

    residual_tier = WaterfallTier(
        "residual_split", remaining * residual_split.lp_pct, remaining * residual_split.gp_pct,
    )

    return _finalize(
        lp_capital=lp_capital, gp_capital=gp_capital,
        tiers=[roc_tier, pref_tier, catchup_tier, residual_tier],
    )


@dataclass(frozen=True)
class CoGpSplit:
    """Section 70 Phase 6: "JV with co-GP profit sharing." Splits an already-computed
    GP profit total among co-GP parties by name -> pct (must sum to 1.0)."""
    shares: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        total = sum(self.shares.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"co-GP shares must sum to 1.0, got {total}")


def apply_co_gp_split(*, gp_total_distribution: float, split: CoGpSplit) -> dict[str, float]:
    return {name: gp_total_distribution * pct for name, pct in split.shares.items()}


def apply_mezzanine_layer(
    *, total_distributable_proceeds: float, mezz_principal: float, mezz_rate: float, mezz_term_years: float,
) -> tuple[float, float]:
    """Section 70 Phase 6: "Mezzanine debt layer." Mezz sits senior to LP/GP equity —
    its bullet repayment (principal + compounded interest over the term) comes out of
    distributable proceeds before the equity waterfall runs at all. Returns
    (equity_distributable_proceeds, mezz_total_repayment)."""
    mezz_total_repayment = mezz_principal * (1 + mezz_rate) ** mezz_term_years
    mezz_paid = min(total_distributable_proceeds, mezz_total_repayment)
    equity_distributable = total_distributable_proceeds - mezz_paid
    return equity_distributable, mezz_paid


def apply_ground_lease(
    *, total_distributable_proceeds: float, ground_rent_annual: float, lease_term_years: float,
) -> tuple[float, float]:
    """Section 70 Phase 6: "Ground lease with residual ownership." The ground lessor
    is a separate stakeholder from the LP/GP equity cap table — ground rent over the
    lease term comes out of distributable proceeds before the leasehold equity
    waterfall runs; land/residual value reverting to the lessor at lease end is not
    part of the leasehold equity holders' distribution. Returns
    (leasehold_distributable_proceeds, total_ground_rent_paid)."""
    total_ground_rent = ground_rent_annual * lease_term_years
    ground_rent_paid = min(total_distributable_proceeds, total_ground_rent)
    leasehold_distributable = total_distributable_proceeds - ground_rent_paid
    return leasehold_distributable, ground_rent_paid
