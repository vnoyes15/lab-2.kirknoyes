"""Lender Package Generation API — Section 71."""
from fastapi import APIRouter, Depends, HTTPException, status

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.lender_package import build_lender_package

router = APIRouter(prefix="/api/v1/deals", tags=["lender-package"])


@router.get("/{deal_id}/lender-package")
def get_lender_package(
    deal_id: str, user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        package = build_lender_package(conn, deal_id)
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    return package
