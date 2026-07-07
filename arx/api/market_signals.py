"""Market Signal Processing API — Section 62."""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.market_signals import create_market_signal, list_market_signals, route_signal_to_deals

router = APIRouter(prefix="/api/v1/market-signals", tags=["market-signals"])

SIGNAL_TYPES = ("interest_rate", "cap_rate", "employment", "permit_activity", "comparable_sale", "population_migration")
SIGNIFICANCE_LEVELS = ("low", "medium", "high")


class MarketSignalRequest(BaseModel):
    signal_type: Literal[SIGNAL_TYPES]
    submarket: str | None = None
    signal_value: float
    prior_value: float | None = None
    source: str | None = None
    significance: Literal[SIGNIFICANCE_LEVELS] | None = None


@router.post("")
def post_market_signal(
    payload: MarketSignalRequest, user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        with conn.transaction():
            signal_id = create_market_signal(
                conn, org_id=user.org_id, signal_type=payload.signal_type, submarket=payload.submarket,
                signal_value=payload.signal_value, prior_value=payload.prior_value,
                source=payload.source, significance=payload.significance,
            )
            affected_deal_ids = route_signal_to_deals(conn, org_id=user.org_id, signal_id=signal_id)

    return {"signal_id": signal_id, "affected_deal_ids": affected_deal_ids}


@router.get("")
def get_market_signals(
    submarket: str | None = None, user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        return list_market_signals(conn, user.org_id, submarket=submarket)
