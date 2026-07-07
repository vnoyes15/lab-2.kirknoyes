"""JV & Complex Equity Structure Modeling API — Section 70. One endpoint dispatches on
structure_type to the matching pure function in arx/agents/equity_waterfall.py, then
persists both the request and the computed result (arx/db/queries/equity_waterfalls.py)
— same "every run is a record" pattern as scenario modeling (Section 63).

Mezzanine and ground_lease compose with the simple_lp_gp equity waterfall specifically
(the layer senior to equity is applied first, then the same promote-based structure
runs on what's left) rather than allowing arbitrary composition with preferred_equity
too — a deliberately bounded scope, not an oversight.
"""
from typing import Annotated, Literal, Union

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field

from arx.agents.equity_waterfall import (
    CoGpSplit,
    SplitRatio,
    apply_co_gp_split,
    apply_ground_lease,
    apply_mezzanine_layer,
    preferred_equity_waterfall,
    simple_lp_gp_waterfall,
)
from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.equity_waterfalls import list_equity_waterfalls, record_equity_waterfall

router = APIRouter(prefix="/api/v1/deals", tags=["equity-waterfall"])


class SimpleLpGpRequest(BaseModel):
    structure_type: Literal["simple_lp_gp"] = "simple_lp_gp"
    lp_capital: float = Field(gt=0)
    gp_capital: float = Field(gt=0)
    total_distributable_proceeds: float = Field(ge=0)
    hurdle_moic: float = Field(gt=1)
    base_split_lp_pct: float
    base_split_gp_pct: float
    promote_split_lp_pct: float
    promote_split_gp_pct: float


class PreferredEquityRequest(BaseModel):
    structure_type: Literal["preferred_equity"] = "preferred_equity"
    lp_capital: float = Field(gt=0)
    gp_capital: float = Field(gt=0)
    total_distributable_proceeds: float = Field(ge=0)
    pref_rate: float = Field(gt=0)
    hold_period_years: float = Field(gt=0)
    catch_up_pct: float = Field(ge=0, lt=1)
    residual_split_lp_pct: float
    residual_split_gp_pct: float


class JvCoGpRequest(BaseModel):
    structure_type: Literal["jv_co_gp"] = "jv_co_gp"
    lp_capital: float = Field(gt=0)
    gp_capital: float = Field(gt=0)
    total_distributable_proceeds: float = Field(ge=0)
    hurdle_moic: float = Field(gt=1)
    base_split_lp_pct: float
    base_split_gp_pct: float
    promote_split_lp_pct: float
    promote_split_gp_pct: float
    co_gp_shares: dict[str, float]


class MezzanineRequest(BaseModel):
    structure_type: Literal["mezzanine"] = "mezzanine"
    lp_capital: float = Field(gt=0)
    gp_capital: float = Field(gt=0)
    total_distributable_proceeds: float = Field(ge=0)
    mezz_principal: float = Field(gt=0)
    mezz_rate: float = Field(gt=0)
    mezz_term_years: float = Field(gt=0)
    hurdle_moic: float = Field(gt=1)
    base_split_lp_pct: float
    base_split_gp_pct: float
    promote_split_lp_pct: float
    promote_split_gp_pct: float


class GroundLeaseRequest(BaseModel):
    structure_type: Literal["ground_lease"] = "ground_lease"
    lp_capital: float = Field(gt=0)
    gp_capital: float = Field(gt=0)
    total_distributable_proceeds: float = Field(ge=0)
    ground_rent_annual: float = Field(gt=0)
    lease_term_years: float = Field(gt=0)
    hurdle_moic: float = Field(gt=1)
    base_split_lp_pct: float
    base_split_gp_pct: float
    promote_split_lp_pct: float
    promote_split_gp_pct: float


WaterfallRequest = Annotated[
    Union[SimpleLpGpRequest, PreferredEquityRequest, JvCoGpRequest, MezzanineRequest, GroundLeaseRequest],
    Field(discriminator="structure_type"),
]


def _run_waterfall(payload: WaterfallRequest) -> dict:
    if payload.structure_type == "simple_lp_gp":
        result = simple_lp_gp_waterfall(
            lp_capital=payload.lp_capital, gp_capital=payload.gp_capital,
            total_distributable_proceeds=payload.total_distributable_proceeds, hurdle_moic=payload.hurdle_moic,
            base_split=SplitRatio(payload.base_split_lp_pct, payload.base_split_gp_pct),
            promote_split=SplitRatio(payload.promote_split_lp_pct, payload.promote_split_gp_pct),
        )
        return result.to_dict()

    if payload.structure_type == "preferred_equity":
        result = preferred_equity_waterfall(
            lp_capital=payload.lp_capital, gp_capital=payload.gp_capital,
            total_distributable_proceeds=payload.total_distributable_proceeds, pref_rate=payload.pref_rate,
            hold_period_years=payload.hold_period_years, catch_up_pct=payload.catch_up_pct,
            residual_split=SplitRatio(payload.residual_split_lp_pct, payload.residual_split_gp_pct),
        )
        return result.to_dict()

    if payload.structure_type == "jv_co_gp":
        result = simple_lp_gp_waterfall(
            lp_capital=payload.lp_capital, gp_capital=payload.gp_capital,
            total_distributable_proceeds=payload.total_distributable_proceeds, hurdle_moic=payload.hurdle_moic,
            base_split=SplitRatio(payload.base_split_lp_pct, payload.base_split_gp_pct),
            promote_split=SplitRatio(payload.promote_split_lp_pct, payload.promote_split_gp_pct),
        )
        output = result.to_dict()
        output["co_gp_breakdown"] = apply_co_gp_split(
            gp_total_distribution=result.gp_total_distribution, split=CoGpSplit(shares=payload.co_gp_shares),
        )
        return output

    if payload.structure_type == "mezzanine":
        equity_distributable, mezz_paid = apply_mezzanine_layer(
            total_distributable_proceeds=payload.total_distributable_proceeds,
            mezz_principal=payload.mezz_principal, mezz_rate=payload.mezz_rate,
            mezz_term_years=payload.mezz_term_years,
        )
        result = simple_lp_gp_waterfall(
            lp_capital=payload.lp_capital, gp_capital=payload.gp_capital,
            total_distributable_proceeds=equity_distributable, hurdle_moic=payload.hurdle_moic,
            base_split=SplitRatio(payload.base_split_lp_pct, payload.base_split_gp_pct),
            promote_split=SplitRatio(payload.promote_split_lp_pct, payload.promote_split_gp_pct),
        )
        output = result.to_dict()
        output["mezz_total_repayment"] = mezz_paid
        output["equity_distributable_proceeds"] = equity_distributable
        return output

    if payload.structure_type == "ground_lease":
        leasehold_distributable, ground_rent_paid = apply_ground_lease(
            total_distributable_proceeds=payload.total_distributable_proceeds,
            ground_rent_annual=payload.ground_rent_annual, lease_term_years=payload.lease_term_years,
        )
        result = simple_lp_gp_waterfall(
            lp_capital=payload.lp_capital, gp_capital=payload.gp_capital,
            total_distributable_proceeds=leasehold_distributable, hurdle_moic=payload.hurdle_moic,
            base_split=SplitRatio(payload.base_split_lp_pct, payload.base_split_gp_pct),
            promote_split=SplitRatio(payload.promote_split_lp_pct, payload.promote_split_gp_pct),
        )
        output = result.to_dict()
        output["total_ground_rent_paid"] = ground_rent_paid
        output["leasehold_distributable_proceeds"] = leasehold_distributable
        return output

    raise AssertionError(f"unreachable: unknown structure_type {payload.structure_type!r}")  # pragma: no cover


@router.post("/{deal_id}/waterfall", status_code=status.HTTP_201_CREATED)
def create_equity_waterfall(
    deal_id: str, payload: WaterfallRequest = Body(discriminator="structure_type"),
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        cur = conn.execute("select deal_id from deals where deal_id = %s", (deal_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

        try:
            outputs = _run_waterfall(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

        with conn.transaction():
            waterfall_id = record_equity_waterfall(
                conn, deal_id=deal_id, org_id=user.org_id, structure_type=payload.structure_type,
                inputs=payload.model_dump(), outputs=outputs, created_by_user_id=user.user_id,
            )

    return {"waterfall_id": waterfall_id, "deal_id": deal_id, "structure_type": payload.structure_type, **outputs}


@router.get("/{deal_id}/waterfall")
def list_deal_equity_waterfalls(
    deal_id: str, user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        return list_equity_waterfalls(conn, deal_id)
