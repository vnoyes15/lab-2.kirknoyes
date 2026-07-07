"""Deal Risk Monitor — Section 44.

"Monitored risk events [Continuous]. Acquisition deals: DSCR breach from rate
movement, cap rate repricing, DD deadline with open flags, seller distress escalation
post-LOI. Construction deals: budget variance above threshold, schedule delay,
construction loan draw approaching limit, absorption slower than pro forma in lease-up
phase."

Pure deterministic functions, no AI, no DB — same contract as notification_rules.py:
each takes the facts the caller (arx/db/queries/deal_risk.py) already gathered and
returns a RiskFlag or None.

"Absorption slower than pro forma in lease-up phase" is the one risk event NOT
implemented here: there is no tracked actual-absorption/leasing data anywhere in the
schema — that's Section 72 PM2's PM-integration leasing feed, which has no
credentials in this environment (same deferred-external-data pattern as the rest of
Phase 6's PM/market-feed gaps). Documented here rather than fabricated.
"""
from dataclasses import asdict, dataclass

CAP_RATE_REPRICING_THRESHOLD_BPS = 50
# No exact day count is given in the spec for "DD deadline" — 30 days in due_diligence
# with an unresolved flag is a ZONIQ operating-cadence assumption, same category as
# momentum_scoring.py's and notification_rules.py's documented thresholds.
DD_DEADLINE_THRESHOLD_DAYS = 30
SELLER_DISTRESS_SCORE_THRESHOLD = 70
CONSTRUCTION_BUDGET_VARIANCE_THRESHOLD = 0.10
CONSTRUCTION_DRAW_APPROACHING_LIMIT_THRESHOLD = 0.90


@dataclass(frozen=True)
class RiskFlag:
    risk_type: str
    severity: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def dscr_breach_risk(*, dscr_hard_fail: bool, dscr_warning: bool, dscr: float) -> RiskFlag | None:
    if dscr_hard_fail:
        return RiskFlag(risk_type="dscr_breach", severity="critical", detail=f"DSCR {dscr:.2f} is below 1.00.")
    if dscr_warning:
        return RiskFlag(
            risk_type="dscr_breach", severity="warning",
            detail=f"DSCR {dscr:.2f} is below the 1.25 warning threshold.",
        )
    return None


def cap_rate_repricing_risk(*, acquisition_cap_rate: float, current_market_cap_rate: float) -> RiskFlag | None:
    """Flags when the submarket's current average cap rate has repriced wider than the
    deal's own acquisition cap rate by CAP_RATE_REPRICING_THRESHOLD_BPS+ — a signal the
    asset would trade at a lower value if sold today than what it was underwritten at."""
    delta_bps = (current_market_cap_rate - acquisition_cap_rate) * 10_000
    if delta_bps >= CAP_RATE_REPRICING_THRESHOLD_BPS:
        return RiskFlag(
            risk_type="cap_rate_repricing", severity="warning",
            detail=f"Submarket cap rates have widened {delta_bps:.0f}bps since acquisition "
                   f"({acquisition_cap_rate:.2%} -> {current_market_cap_rate:.2%}).",
        )
    return None


def dd_deadline_with_open_flags_risk(
    *, days_in_due_diligence: int, open_flagged_task_count: int,
) -> RiskFlag | None:
    if open_flagged_task_count > 0 and days_in_due_diligence >= DD_DEADLINE_THRESHOLD_DAYS:
        return RiskFlag(
            risk_type="dd_deadline_with_open_flags", severity="critical",
            detail=f"{open_flagged_task_count} flagged due diligence item(s) still open after "
                   f"{days_in_due_diligence} days in due_diligence.",
        )
    return None


def seller_distress_escalation_risk(
    *, motivated_seller_score: int, distress_indicators: list[str],
) -> RiskFlag | None:
    if motivated_seller_score >= SELLER_DISTRESS_SCORE_THRESHOLD and distress_indicators:
        return RiskFlag(
            risk_type="seller_distress_escalation", severity="info",
            detail=f"Seller motivation score {motivated_seller_score}/100 post-LOI: "
                   f"{', '.join(distress_indicators)}.",
        )
    return None


def construction_budget_variance_risk(*, total_budget: float, total_variance: float) -> RiskFlag | None:
    if total_budget <= 0:
        return None
    variance_pct = total_variance / total_budget
    if variance_pct >= CONSTRUCTION_BUDGET_VARIANCE_THRESHOLD:
        return RiskFlag(
            risk_type="budget_variance", severity="warning",
            detail=f"Construction budget variance is {variance_pct:.1%} over budget.",
        )
    return None


def schedule_delay_risk(*, delayed_milestones: list[dict]) -> RiskFlag | None:
    if not delayed_milestones:
        return None
    names = ", ".join(m["milestone_type"] for m in delayed_milestones)
    return RiskFlag(
        risk_type="schedule_delay", severity="warning",
        detail=f"{len(delayed_milestones)} milestone(s) delayed: {names}.",
    )


def construction_draw_approaching_limit_risk(*, total_committed: float, total_drawn: float) -> RiskFlag | None:
    if total_committed <= 0:
        return None
    drawn_pct = total_drawn / total_committed
    if drawn_pct >= CONSTRUCTION_DRAW_APPROACHING_LIMIT_THRESHOLD:
        return RiskFlag(
            risk_type="construction_draw_approaching_limit", severity="warning",
            detail=f"Construction draws are at {drawn_pct:.1%} of committed budget.",
        )
    return None
