"""Attorney Portal API — Section 71. Mirrors arx/api/lp.py's shape: every route
requires role="attorney" AND an explicit deal_attorney_access row (require_role alone
would let an Admin/Analyst token in) — a missing grant 404s, indistinguishable from a
non-existent deal (MT4-style: no signal to a caller about whether a deal exists vs.
they just lack access to it).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.attorney import (
    confirm_legal_review_task,
    create_deal_comment,
    get_attorney_deal_view,
    grant_attorney_access,
    has_attorney_access,
    list_attorney_accessible_deals,
    list_deal_comments,
)

router = APIRouter(prefix="/api/v1/attorney", tags=["attorney"])
deals_router = APIRouter(prefix="/api/v1/deals", tags=["attorney"])


@router.get("/deals")
def attorney_accessible_deals(user: CurrentUser = Depends(require_role("attorney"))) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        return list_attorney_accessible_deals(conn, user.user_id)


@router.get("/deals/{deal_id}")
def attorney_deal_view(deal_id: str, user: CurrentUser = Depends(require_role("attorney"))) -> dict:
    with db_session(claims_for(user)) as conn:
        if not has_attorney_access(conn, deal_id=deal_id, attorney_user_id=user.user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
        return get_attorney_deal_view(conn, deal_id)


class DealCommentRequest(BaseModel):
    body: str = Field(min_length=1)


@router.post("/deals/{deal_id}/comments", status_code=status.HTTP_201_CREATED)
def attorney_create_comment(
    deal_id: str, payload: DealCommentRequest, user: CurrentUser = Depends(require_role("attorney")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        if not has_attorney_access(conn, deal_id=deal_id, attorney_user_id=user.user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
        with conn.transaction():
            comment_id = create_deal_comment(
                conn, deal_id=deal_id, org_id=user.org_id, author_user_id=user.user_id,
                author_role="attorney", body=payload.body,
            )
    return {"comment_id": comment_id, "deal_id": deal_id}


@router.patch("/deals/{deal_id}/tasks/{task_id}/confirm")
def attorney_confirm_legal_review_task(
    deal_id: str, task_id: str, user: CurrentUser = Depends(require_role("attorney")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        if not has_attorney_access(conn, deal_id=deal_id, attorney_user_id=user.user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
        with conn.transaction():
            task = confirm_legal_review_task(conn, deal_id=deal_id, task_id=task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No legal-review task matching that id was found for this deal",
        )
    return task


# --------------------------------------------------------------- Admin-facing grant/read ---

class AttorneyAccessGrantRequest(BaseModel):
    attorney_user_id: str


@deals_router.post("/{deal_id}/attorney-access", status_code=status.HTTP_201_CREATED)
def grant_deal_attorney_access(
    deal_id: str, payload: AttorneyAccessGrantRequest, user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Section 71: "Access granted per deal by Admin.\""""
    with db_session(claims_for(user)) as conn:
        with conn.cursor() as cur:
            cur.execute("select deal_id from deals where deal_id = %s", (deal_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
        with conn.transaction():
            access_id = grant_attorney_access(
                conn, deal_id=deal_id, org_id=user.org_id, attorney_user_id=payload.attorney_user_id,
                granted_by_user_id=user.user_id,
            )
    return {"access_id": access_id, "deal_id": deal_id, "attorney_user_id": payload.attorney_user_id}


@deals_router.get("/{deal_id}/comments")
def get_deal_comments(
    deal_id: str, user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        return list_deal_comments(conn, deal_id)
