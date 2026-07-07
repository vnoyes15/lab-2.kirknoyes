"""Refinance & Disposition Engine — Section 46.

"Refi trigger: when refi improves debt constant by 50bps+, surfaces notification with
projected cash-on-cash improvement. Disposition trigger: cap rate compression implies
value appreciation above return threshold. 1031 Exchange window calculation: 45-day
identification and 180-day close windows calculated when disposition is being
considered."

Pure deterministic functions, no AI, no DB — same contract as scenario_modeling.py and
portfolio_stress.py. Both triggers need an input this environment has no live feed
for (a proposed refi rate, a current market cap rate) — Section 07 Phase 6 lists
"interest rate feeds" and "county assessor APIs" as external integrations this sandbox
has no credentials for (same deferred-external-data pattern as PM integration and
market signal feeds elsewhere in Phase 6). So these are caller-supplied analysis
inputs to an on-demand endpoint rather than an automatic nightly job like momentum
scoring — there's nothing to poll without a real rate/comp feed behind it.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from arx.agents.loan_math import compute_annual_debt_service

REFI_DEBT_CONSTANT_IMPROVEMENT_THRESHOLD_BPS = 50
# No exact number is given for the disposition "return threshold" — 15% implied value
# appreciation is a ZONIQ operating-cadence assumption, same category as this
# codebase's other documented thresholds (momentum_scoring.py, notification_rules.py).
DEFAULT_DISPOSITION_APPRECIATION_THRESHOLD = 0.15

IDENTIFICATION_WINDOW_DAYS = 45
CLOSE_WINDOW_DAYS = 180


def debt_constant(*, annual_debt_service: float, loan_amount: float) -> float:
    return annual_debt_service / loan_amount


@dataclass(frozen=True)
class RefiAnalysis:
    original_debt_constant: float
    proposed_debt_constant: float
    improvement_bps: float
    original_cash_on_cash: float
    projected_cash_on_cash: float
    cash_on_cash_improvement: float
    triggers_refi_opportunity: bool


def analyze_refi(
    *, baseline: dict, proposed_interest_rate: float, proposed_amortization_years: int | None = None,
) -> RefiAnalysis:
    """baseline is the deal's active A-02 snapshot output_payload (Section 87
    A02Output). Loan amount and NOI are held constant — only the rate (and optionally
    the amortization schedule) change under a refi."""
    amortization_years = proposed_amortization_years or baseline["amortization_years"]
    original_debt_service = baseline["annual_debt_service"]
    proposed_debt_service = compute_annual_debt_service(
        baseline["loan_amount"], proposed_interest_rate, amortization_years,
    )

    original_dc = debt_constant(annual_debt_service=original_debt_service, loan_amount=baseline["loan_amount"])
    proposed_dc = debt_constant(annual_debt_service=proposed_debt_service, loan_amount=baseline["loan_amount"])
    improvement_bps = (original_dc - proposed_dc) * 10_000

    equity = baseline["purchase_price"] * (1 - baseline["ltv"])
    original_coc = (baseline["noi"] - original_debt_service) / equity
    projected_coc = (baseline["noi"] - proposed_debt_service) / equity

    return RefiAnalysis(
        original_debt_constant=original_dc, proposed_debt_constant=proposed_dc,
        improvement_bps=improvement_bps,
        original_cash_on_cash=original_coc, projected_cash_on_cash=projected_coc,
        cash_on_cash_improvement=projected_coc - original_coc,
        triggers_refi_opportunity=improvement_bps >= REFI_DEBT_CONSTANT_IMPROVEMENT_THRESHOLD_BPS,
    )


@dataclass(frozen=True)
class DispositionAnalysis:
    original_value: float
    implied_value: float
    appreciation_pct: float
    triggers_disposition_opportunity: bool


def analyze_disposition(
    *, baseline: dict, current_market_cap_rate: float,
    appreciation_threshold: float = DEFAULT_DISPOSITION_APPRECIATION_THRESHOLD,
) -> DispositionAnalysis:
    """baseline is the deal's active A-02 snapshot output_payload. Cap rate compression
    (current_market_cap_rate < the deal's acquisition cap_rate) implies the asset would
    sell for more than it was bought for, at the same NOI."""
    original_value = baseline["purchase_price"]
    implied_value = baseline["noi"] / current_market_cap_rate
    appreciation_pct = (implied_value - original_value) / original_value

    return DispositionAnalysis(
        original_value=original_value, implied_value=implied_value, appreciation_pct=appreciation_pct,
        triggers_disposition_opportunity=appreciation_pct >= appreciation_threshold,
    )


@dataclass(frozen=True)
class Section1031Windows:
    identification_deadline: date
    close_deadline: date


def compute_1031_windows(disposition_date: date) -> Section1031Windows:
    return Section1031Windows(
        identification_deadline=disposition_date + timedelta(days=IDENTIFICATION_WINDOW_DAYS),
        close_deadline=disposition_date + timedelta(days=CLOSE_WINDOW_DAYS),
    )
