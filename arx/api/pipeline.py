"""Pipeline View API — Section 20.

GET /api/v1/pipeline (not nested under /deals — a distinct top-level resource per the
spec) with filters: status, deal_type, assigned_user_id, date range, submarket. Dead
deals excluded by default. GET /api/v1/pipeline/analytics: death reason distribution,
average days per stage, deal type breakdown.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.pipeline import get_pipeline_analytics, get_pipeline_view

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


@router.get("")
def pipeline_view(
    status: str | None = Query(default=None, alias="status"),
    deal_type: str | None = None,
    assigned_user_id: str | None = None, submarket: str | None = None,
    created_after: date | None = None, created_before: date | None = None,
    user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> list[dict]:
    """Section 06/23: deals for the caller's org, grouped into pipeline stage order
    with momentum_score/days_in_current_status attached (see
    arx/db/queries/pipeline.py, arx/agents/momentum_scoring.py). Scores reflect
    whatever arx.tasks.momentum_scorer's last nightly run computed — this endpoint
    reads, it never recomputes inline (that stays a background-job concern, not
    request-latency work)."""
    with db_session(claims_for(user)) as conn:
        return get_pipeline_view(
            conn, user.org_id, status_filter=status, deal_type=deal_type,
            assigned_user_id=assigned_user_id, submarket=submarket,
            created_after=created_after.isoformat() if created_after else None,
            created_before=created_before.isoformat() if created_before else None,
        )


@router.get("/analytics")
def pipeline_analytics(user: CurrentUser = Depends(require_role("admin", "analyst", "viewer"))) -> dict:
    with db_session(claims_for(user)) as conn:
        return get_pipeline_analytics(conn, user.org_id)
