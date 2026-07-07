"""Deal Risk Monitor API — Section 44. Read-only: risk flags are computed live from
current deal/snapshot/task/budget state on every request (arx/db/queries/deal_risk.py)
rather than persisted, since Section 44 calls this "continuous" monitoring — there's
no separate table of past risk events to page through, only current state.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.deal_risk import evaluate_deal_risk, list_org_deal_risk

router = APIRouter(prefix="/api/v1", tags=["risk"])


@router.get("/deals/{deal_id}/risk")
def get_deal_risk(
    deal_id: str, user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        result = evaluate_deal_risk(conn, deal_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    return result


@router.get("/portfolio/risk-monitor")
def portfolio_risk_monitor(
    user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        return list_org_deal_risk(conn, user.org_id)
