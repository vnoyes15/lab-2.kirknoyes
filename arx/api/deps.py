"""Shared FastAPI route helpers."""
from arx.api.auth import CurrentUser


def claims_for(user: CurrentUser) -> dict:
    return {"org_id": user.org_id, "role": user.role, "sub": user.user_id}
