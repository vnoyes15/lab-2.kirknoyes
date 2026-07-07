"""Notifications API — Section 06. Read/mark-read only; notifications are created by
the trigger points documented in arx/agents/notification_rules.py (A-06's endpoint,
A-08's endpoint, arx/tasks/momentum_scorer.py), never by a direct client write.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.notifications import list_notifications, mark_notification_read

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("")
def get_notifications(
    unread_only: bool = False,
    user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        return list_notifications(conn, user.org_id, unread_only=unread_only)


@router.post("/{notification_id}/read")
def read_notification(
    notification_id: str,
    user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        with conn.transaction():
            found = mark_notification_read(conn, user.org_id, notification_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return {"notification_id": notification_id, "is_read": True}
