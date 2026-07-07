"""LP Trust Layer API — Section 49.

Every endpoint here requires role="lp" (Section 09's three roles predate this v1.5
addition — see arx/api/auth.py's docstring) AND an explicit deal_lp_access row for the
requesting user. Both checks are mandatory: role alone would let any LP query any
deal; deal_lp_access alone would let an Admin/Analyst token in. "Zero cross-deal
visibility" (Section 49) means an LP with no access row gets a 404, not a 403 —
indistinguishable from the deal not existing, same MT4 reasoning already applied to
cross-org access everywhere else in the API.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.lp import (
    generate_lp_quarterly_report,
    get_lp_deal_view,
    has_lp_access,
    list_lp_accessible_deals,
)

router = APIRouter(prefix="/api/v1/lp", tags=["lp"])


@router.get("/deals")
def lp_accessible_deals(user: CurrentUser = Depends(require_role("lp"))) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        return list_lp_accessible_deals(conn, user.user_id)


@router.get("/deals/{deal_id}")
def lp_deal_view(deal_id: str, user: CurrentUser = Depends(require_role("lp"))) -> dict:
    with db_session(claims_for(user)) as conn:
        if not has_lp_access(conn, deal_id=deal_id, lp_user_id=user.user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
        return get_lp_deal_view(conn, deal_id)


@router.get("/report/{deal_id}")
def lp_quarterly_report(deal_id: str, period: str, user: CurrentUser = Depends(require_role("lp"))) -> dict:
    with db_session(claims_for(user)) as conn:
        if not has_lp_access(conn, deal_id=deal_id, lp_user_id=user.user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
        try:
            return generate_lp_quarterly_report(conn, deal_id=deal_id, period=period)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
