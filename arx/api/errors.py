"""Error log API — Section 78 EP2: "resolution_status and resolution_notes tracked
through to closure." record_error (arx/db/queries/quality_log.py) writes every
unrecoverable agent failure; this is the Admin-facing view/workflow on top of it.
Admin-only — resolving errors is an operational/oversight task, same tier as billing
and config (Section 09), not something an Analyst or Viewer role does.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.quality_log import list_errors, update_error_resolution

router = APIRouter(prefix="/api/v1/errors", tags=["errors"])

RESOLUTION_STATUSES = ("open", "investigating", "resolved")


@router.get("")
def get_errors(
    resolution_status: Literal[RESOLUTION_STATUSES] | None = None,
    user: CurrentUser = Depends(require_role("admin")),
) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        return list_errors(conn, user.org_id, resolution_status=resolution_status)


class ErrorResolutionUpdateRequest(BaseModel):
    resolution_status: Literal[RESOLUTION_STATUSES]
    resolution_notes: str | None = None


@router.patch("/{error_id}")
def update_error(
    error_id: str, payload: ErrorResolutionUpdateRequest,
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        with conn.transaction():
            updated = update_error_resolution(
                conn, org_id=user.org_id, error_id=error_id,
                resolution_status=payload.resolution_status, resolution_notes=payload.resolution_notes,
            )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Error record not found")
    return updated
