"""Refinance & Disposition Engine API — Section 46. On-demand analysis endpoints: both
triggers depend on an input this environment has no live feed for (a proposed refi
rate, a current market cap rate) — see arx/agents/refi_disposition.py's module
docstring. A notification only fires once the deterministic trigger condition is
actually met, never unconditionally.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row
from pydantic import BaseModel

from arx.agents.notification_rules import disposition_opportunity_notification, refi_opportunity_notification
from arx.agents.refi_disposition import (
    DEFAULT_DISPOSITION_APPRECIATION_THRESHOLD,
    analyze_disposition,
    analyze_refi,
    compute_1031_windows,
)
from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.notifications.channels import InAppChannel

router = APIRouter(prefix="/api/v1/deals", tags=["refi-disposition"])


def _get_deal_and_active_a02(conn, deal_id: str) -> tuple[dict, dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select deal_id, property_address from deals where deal_id = %s", (deal_id,))
        deal = cur.fetchone()
    if deal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select output_payload from deal_snapshots "
            "where deal_id = %s and agent_id = 'a02' and is_active = true",
            (deal_id,),
        )
        snapshot = cur.fetchone()
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active A-02 snapshot for this deal — refi/disposition analysis needs the deal's underwriting.",
        )
    return deal, snapshot["output_payload"]


class RefiAnalysisRequest(BaseModel):
    proposed_interest_rate: float
    proposed_amortization_years: int | None = None


@router.post("/{deal_id}/refi-analysis")
def refi_analysis(
    deal_id: str, payload: RefiAnalysisRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        deal, baseline = _get_deal_and_active_a02(conn, deal_id)
        result = analyze_refi(
            baseline=baseline, proposed_interest_rate=payload.proposed_interest_rate,
            proposed_amortization_years=payload.proposed_amortization_years,
        )
        if result.triggers_refi_opportunity:
            spec = refi_opportunity_notification(
                property_address=deal["property_address"], improvement_bps=result.improvement_bps,
                cash_on_cash_improvement=result.cash_on_cash_improvement,
            )
            with conn.transaction():
                InAppChannel().send(conn, org_id=user.org_id, spec=spec, deal_id=deal_id)

    return {"deal_id": deal_id, **result.__dict__}


class DispositionAnalysisRequest(BaseModel):
    current_market_cap_rate: float
    appreciation_threshold: float = DEFAULT_DISPOSITION_APPRECIATION_THRESHOLD
    disposition_date: date | None = None


@router.post("/{deal_id}/disposition-analysis")
def disposition_analysis(
    deal_id: str, payload: DispositionAnalysisRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        deal, baseline = _get_deal_and_active_a02(conn, deal_id)
        result = analyze_disposition(
            baseline=baseline, current_market_cap_rate=payload.current_market_cap_rate,
            appreciation_threshold=payload.appreciation_threshold,
        )
        if result.triggers_disposition_opportunity:
            spec = disposition_opportunity_notification(
                property_address=deal["property_address"], appreciation_pct=result.appreciation_pct,
            )
            with conn.transaction():
                InAppChannel().send(conn, org_id=user.org_id, spec=spec, deal_id=deal_id)

    windows = compute_1031_windows(payload.disposition_date or date.today())

    return {
        "deal_id": deal_id, **result.__dict__,
        "section_1031_windows": {
            "identification_deadline": windows.identification_deadline.isoformat(),
            "close_deadline": windows.close_deadline.isoformat(),
        },
    }
