"""Daily Intelligence Brief API — Section 40."""
from fastapi import APIRouter, Depends

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.daily_brief import build_daily_brief

router = APIRouter(prefix="/api/v1/brief", tags=["intelligence"])


@router.get("")
def get_daily_brief(user: CurrentUser = Depends(require_role("admin", "analyst"))) -> dict:
    """Section 40: "Personalized per user — Analyst sees assigned deals, Admin sees
    full org picture." On-demand read; the 6am scheduled push is deferred (no email/
    SMS provider configured — see arx/db/queries/daily_brief.py's module docstring)."""
    with db_session(claims_for(user)) as conn:
        return build_daily_brief(conn, org_id=user.org_id, user_id=user.user_id, role=user.role)
