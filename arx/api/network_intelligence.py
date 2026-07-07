"""Network Intelligence Layer API — Section 59."""
import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from arx.api.auth import CurrentUser, require_role
from arx.api.config import get_settings
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.network_intelligence import (
    NetworkContributionError,
    contribute_deal_to_network,
    get_network_comps,
    get_network_status,
)

router = APIRouter(prefix="/api/v1", tags=["network-intelligence"])


class NetworkContributionRequest(BaseModel):
    consent: bool
    financing_type: str | None = None


@router.post("/deals/{deal_id}/network-contribution", status_code=status.HTTP_201_CREATED)
def post_network_contribution(
    deal_id: str, payload: NetworkContributionRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        try:
            with conn.transaction():
                contribution_id = contribute_deal_to_network(
                    conn, org_id=user.org_id, deal_id=deal_id, user_consent=payload.consent,
                    financing_type=payload.financing_type,
                )
        except NetworkContributionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return {"contribution_id": contribution_id, "deal_id": deal_id}


class NetworkOptInRequest(BaseModel):
    network_participation: bool


@router.patch("/org/network-opt-in")
def patch_network_opt_in(
    payload: NetworkOptInRequest, user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        with conn.transaction():
            conn.execute(
                "update orgs set network_participation = %s where org_id = %s",
                (payload.network_participation, user.org_id),
            )
    return {"org_id": user.org_id, "network_participation": payload.network_participation}


def _superuser_conn() -> psycopg.Connection:
    settings = get_settings()
    return psycopg.connect(settings.database_url, autocommit=True)


@router.get("/network-intelligence/status")
def network_intelligence_status(
    user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> dict:
    with _superuser_conn() as conn:
        return get_network_status(conn)


@router.get("/network-intelligence/comps")
def network_intelligence_comps(
    submarket: str, asset_type: str | None = None,
    user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> dict:
    with _superuser_conn() as conn:
        return get_network_comps(conn, submarket=submarket, asset_type=asset_type)
