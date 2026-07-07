"""Auth & role enforcement — Section 09 + Section 49 + Section 71.

Section 09 (Tier 2, written before the v1.5 LP Trust Layer addition) names three
roles: Admin (full access, billing, config), Analyst (run agents, create deals,
no billing/settings), Viewer (read-only — deal memos and underwriting only, no seller
profiles). Section 49 (v1.5, Tier 4) then introduces a fourth: "LP Viewer role scoped
to specific deals via deal_lp_access table... Zero cross-deal visibility." An LP is
architecturally distinct from the org's own internal Viewer role — a Viewer sees every
deal in the org (minus seller profiles); an LP is an external investor who must see
*only* the specific deal(s) they're invested in, and only the LP-visible subset of
fields on those (Section 49: LP-hidden covers seller profiles, internal comments,
assumption overrides, offer strategy details). Modeling "lp" as its own role rather
than a restricted Viewer keeps that hard boundary in the role check itself rather than
relying on every LP-facing endpoint to remember an extra filter.

Section 71 (Phase 6) adds a fifth: "attorney" — same deal-scoped-access shape as "lp"
(deal_attorney_access mirrors deal_lp_access), but a completely different visible
field set: documents relevant to legal review and the A-06 legal checklist, never
financial details, seller profiles, or outreach history (all of which an LP token
*can* see a curated slice of). Two separate external-party roles rather than one
generic "external" role, for the same reason lp isn't a restricted Viewer: the
visible-field boundary lives in the role check, not in per-endpoint filtering logic
an engineer could forget to add later.

MT3: "Role enforcement at API layer regardless of front end. Viewer token on agent
endpoint = 403." This module is that enforcement point — every router dependency-injects
`require_role(...)` rather than trusting anything the front end sends.

DESIGN NOTE for the engineer picking this up: Supabase Auth issues the session JWT.
This scaffold verifies it as a symmetric HS256 token against SECRET_KEY, which matches
Supabase's legacy shared-secret JWT signing. If the Supabase project instead uses
asymmetric (ES256/RS256) signing keys, swap `jwt.decode(..., algorithms=["HS256"])`
below for JWKS verification via Supabase's `/auth/v1/.well-known/jwks.json` — every
call site here goes through `get_current_user`, so it's a one-function change.

org_id and role are expected as custom claims on that JWT (configured via a Supabase
Auth Hook / custom access token hook — out of scope for Phase 1 code, but required
before Phase 2 real users exist). MT2: prompt templates are platform-level; deal data
is org-scoped — never confuse the two when reading claims here.
"""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from arx.api.config import get_settings

security = HTTPBearer()

Role = str  # "admin" | "analyst" | "viewer" | "lp" | "attorney"
VALID_ROLES: tuple[Role, ...] = ("admin", "analyst", "viewer", "lp", "attorney")


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    org_id: str
    role: Role


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> CurrentUser:
    settings = get_settings()
    token = credentials.credentials

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    org_id = payload.get("org_id")
    role = payload.get("role")
    user_id = payload.get("sub")

    if not org_id or not role or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claims (sub, org_id, role)",
        )
    if role not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Unknown role: {role}")

    return CurrentUser(user_id=user_id, org_id=org_id, role=role)


def require_role(*allowed_roles: Role):
    """Route dependency factory. Usage: Depends(require_role("admin", "analyst")).

    MT3 is explicit that this check happens "regardless of front end" — it lives here,
    not in any UI, and applies even though Phase 1 has no front end at all (Section 01:
    "API-first. No front end in Phase 1.").
    """

    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' cannot access this endpoint (requires one of {allowed_roles})",
            )
        return user

    return _check
