"""Audit & Compliance Report API — Section 57. Also hosts the assumption-override
endpoint (Section 21) — Phase 1 built the `financials` table's override columns but
Phase 2-4 never wired a path for a user to actually record one, so "every assumption
and override" in the audit report had nothing user-provided to show.
"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.audit_report import build_audit_report

router = APIRouter(prefix="/api/v1/deals/{deal_id}", tags=["audit"])


@router.get("/audit-report")
def get_audit_report(
    deal_id: str, format: str | None = None,
    user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> dict:
    if format == "pdf":
        # Section 57: "?format=pdf stores to vault." No PDF rendering library is wired
        # in this environment — same category of gap as email/SMS notification
        # delivery (arx/notifications/channels.py). Reject explicitly rather than
        # silently returning JSON for a caller who asked for a PDF.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF export is not implemented (no PDF rendering library configured). Omit ?format=pdf for JSON.",
        )

    with db_session(claims_for(user)) as conn:
        report = build_audit_report(conn, deal_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    return report


class AssumptionOverrideRequest(BaseModel):
    input_field: str
    input_value: dict | list | str | float | int | bool
    financial_track: Literal["acquisition", "development"]
    override_note: str = Field(min_length=10)


@router.post("/assumption-overrides", status_code=status.HTTP_201_CREATED)
def create_assumption_override(
    deal_id: str, payload: AssumptionOverrideRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    """Section 21: "Every default override writes override_by_user_id, override_note
    (required, min 10 chars, blank rejected at API), and assumption_type =
    user_provided to financials table." Pydantic's Field(min_length=10) is the API-layer
    rejection; the financials table's own chk_override_note_when_overridden constraint
    is defense in depth, same pattern as everywhere else overrides are enforced twice."""
    with db_session(claims_for(user)) as conn:
        with conn.transaction():
            row = conn.execute(
                """
                insert into financials (deal_id, org_id, input_field, input_value,
                                         assumption_type, financial_track, override_by_user_id, override_note)
                values (%s, %s, %s, %s, 'user_provided', %s, %s, %s)
                returning financial_id
                """,
                (deal_id, user.org_id, payload.input_field, json.dumps(payload.input_value),
                 payload.financial_track, user.user_id, payload.override_note),
            ).fetchone()

    return {"financial_id": str(row[0]), "input_field": payload.input_field}
