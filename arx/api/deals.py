"""Deal Intake API — Section 19.

POST /api/v1/deals/intake. Required: property_address, source, org_id, deal_type.
Deduplication: same address + org_id + non-dead status returns the existing deal_id
rather than creating a duplicate. That guarantee is enforced by the database (the
partial unique index uq_deals_org_address_active in
arx/db/migrations/005_deals.sql), not by an application-level "check then insert" —
this endpoint attempts the insert and falls back to a lookup on conflict, so the
guarantee holds even under two concurrent intake calls for the same address.

Not yet implemented (later phases, noted so nobody mistakes silence for an oversight):
  - Documents attached to intake triggering A-09 automatically (R6, Phase 2).
  - Geocoding property_address -> lat/lng (Section 19, Phase 4 per VL5).
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import errors as psycopg_errors
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from arx.api.auth import CurrentUser, require_role
from arx.db.connection import db_session

router = APIRouter(prefix="/api/v1/deals", tags=["deals"])

DealType = Literal["acquisition", "land", "development"]


class DealIntakeRequest(BaseModel):
    property_address: str = Field(min_length=1)
    source: str = Field(min_length=1)
    org_id: str
    deal_type: DealType

    asset_type: str | None = None
    unit_count: int | None = Field(default=None, gt=0)
    land_area_sf: float | None = Field(default=None, gt=0)
    asking_price: float | None = Field(default=None, ge=0)


class DealIntakeResponse(BaseModel):
    deal_id: str
    created: bool  # False when this call deduplicated onto an existing deal


def _claims(user: CurrentUser) -> dict:
    return {"org_id": user.org_id, "role": user.role, "sub": user.user_id}


@router.post("/intake", response_model=DealIntakeResponse, status_code=status.HTTP_201_CREATED)
def create_deal(
    payload: DealIntakeRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> DealIntakeResponse:
    # MT1: org_id is never trusted from the request body alone — it must match the
    # authenticated session. RLS would reject a mismatched insert regardless (defense
    # in depth), but failing fast here gives a clear 403 instead of an opaque DB error.
    if payload.org_id != user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="org_id in request body must match the authenticated session's org",
        )

    with db_session(_claims(user)) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                with conn.transaction():
                    cur.execute(
                        """
                        insert into deals (org_id, property_address, source, deal_type,
                                           asset_type, unit_count, land_area_sf, asking_price)
                        values (%(org_id)s, %(property_address)s, %(source)s, %(deal_type)s,
                                %(asset_type)s, %(unit_count)s, %(land_area_sf)s, %(asking_price)s)
                        returning deal_id
                        """,
                        {
                            "org_id": user.org_id,
                            "property_address": payload.property_address,
                            "source": payload.source,
                            "deal_type": payload.deal_type,
                            "asset_type": payload.asset_type,
                            "unit_count": payload.unit_count,
                            "land_area_sf": payload.land_area_sf,
                            "asking_price": payload.asking_price,
                        },
                    )
                    row = cur.fetchone()
                return DealIntakeResponse(deal_id=str(row["deal_id"]), created=True)
            except psycopg_errors.UniqueViolation:
                cur.execute(
                    """
                    select deal_id from deals
                    where org_id = %(org_id)s and property_address = %(property_address)s
                      and status <> 'dead'
                    """,
                    {"org_id": user.org_id, "property_address": payload.property_address},
                )
                row = cur.fetchone()
                if row is None:
                    # A unique violation fired but no matching non-dead row exists — the
                    # conflict was on something else. Don't paper over it with a fake 200.
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Deal intake conflict could not be resolved to an existing deal",
                    )
                return DealIntakeResponse(deal_id=str(row["deal_id"]), created=False)


@router.get("/{deal_id}")
def get_deal(deal_id: str, user: CurrentUser = Depends(require_role("admin", "analyst", "viewer"))):
    with db_session(_claims(user)) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select * from deals where deal_id = %s", (deal_id,))
            row = cur.fetchone()
    if row is None:
        # RLS means this also fires for another org's deal_id — indistinguishable from
        # "does not exist" by design (MT4: zero cross-org leakage, including via error
        # message differences).
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    return row
