"""Data Quality Engine + Feedback Loop health reporting API — Sections 51 and 76 FL4.
Both are "nightly job" / "monthly report" concepts (Section 51, Section 76) exposed
on-demand here rather than as an actual Celery Beat job — same deferred-scheduling
gap as the rest of this platform's intelligence jobs (see arx/tasks/celery_app.py's
module docstring): the computation is real, only the automatic cadence is missing.
Admin-only, since both are explicitly operational/oversight reports for Admin.
"""
from fastapi import APIRouter, Depends

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.data_quality import get_feedback_loop_health, run_data_quality_checks

router = APIRouter(prefix="/api/v1", tags=["data-quality"])


@router.get("/data-quality/report")
def data_quality_report(user: CurrentUser = Depends(require_role("admin"))) -> dict:
    with db_session(claims_for(user)) as conn:
        return run_data_quality_checks(conn, user.org_id)


@router.get("/feedback-loop/health")
def feedback_loop_health(user: CurrentUser = Depends(require_role("admin"))) -> dict:
    with db_session(claims_for(user)) as conn:
        return get_feedback_loop_health(conn, user.org_id)
