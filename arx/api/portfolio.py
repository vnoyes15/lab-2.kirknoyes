"""Portfolio Layer API — Section 29. Milestone updates also live here (Section 49's
LP milestone-delay notification needs a real write path to development_milestones,
which nothing before Phase 5 provided)."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row
from pydantic import BaseModel

from arx.agents.notification_rules import milestone_delay_notification, performance_variance_notification
from arx.agents.portfolio_stress import StressParams
from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.portfolio import (
    get_active_a02_noi,
    get_development_pipeline,
    get_portfolio_summary,
    list_deal_performance,
    record_deal_performance,
    run_portfolio_stress_test,
)
from arx.notifications.channels import InAppChannel

router = APIRouter(prefix="/api/v1", tags=["portfolio"])


class DealPerformanceRequest(BaseModel):
    period: date  # any day in the month is fine; stored as-is, first-of-month convention is a caller norm
    actual_gross_rent: float | None = None
    actual_vacancy_rate: float | None = None
    actual_noi: float | None = None
    actual_operating_expenses: float | None = None
    notes: str | None = None
    data_source: Literal["manual", "pm_integration"] = "manual"


@router.post("/deals/{deal_id}/performance", status_code=status.HTTP_201_CREATED)
def create_deal_performance(
    deal_id: str, payload: DealPerformanceRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    """Section 29: performance actuals only make sense once a deal is owned. Section 45:
    actual NOI is compared against the active A-02 snapshot's projected NOI here —
    variance above 10% notifies, above 20% escalates to Admin (severity critical)."""
    with db_session(claims_for(user)) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select is_acquired, property_address from deals where deal_id = %s", (deal_id,))
            deal = cur.fetchone()
        if deal is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
        if not deal["is_acquired"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Deal is not yet acquired (is_acquired=false) — no portfolio performance to record (Section 29)",
            )

        variance_pct = None
        with conn.transaction():
            performance_id = record_deal_performance(
                conn, deal_id=deal_id, org_id=user.org_id, period=payload.period.isoformat(),
                actual_gross_rent=payload.actual_gross_rent, actual_vacancy_rate=payload.actual_vacancy_rate,
                actual_noi=payload.actual_noi, actual_operating_expenses=payload.actual_operating_expenses,
                notes=payload.notes, created_by_user_id=user.user_id, data_source=payload.data_source,
            )

            if payload.actual_noi is not None:
                projected_noi = get_active_a02_noi(conn, deal_id)
                if projected_noi is not None and projected_noi != 0:
                    variance_pct = (payload.actual_noi - projected_noi) / projected_noi
                    spec = performance_variance_notification(
                        property_address=deal["property_address"], actual_noi=payload.actual_noi,
                        projected_noi=projected_noi, variance_pct=variance_pct,
                    )
                    if spec is not None:
                        InAppChannel().send(conn, org_id=user.org_id, spec=spec, deal_id=deal_id)

    return {
        "performance_id": performance_id, "deal_id": deal_id, "period": payload.period.isoformat(),
        "variance_pct": variance_pct,
    }


@router.get("/deals/{deal_id}/performance")
def get_deal_performance(
    deal_id: str, user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        return list_deal_performance(conn, deal_id)


@router.get("/portfolio")
def portfolio_summary(user: CurrentUser = Depends(require_role("admin", "analyst", "viewer"))) -> dict:
    with db_session(claims_for(user)) as conn:
        return get_portfolio_summary(conn, user.org_id)


@router.get("/portfolio/development")
def portfolio_development_pipeline(
    user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        return get_development_pipeline(conn, user.org_id)


class StressTestRequest(BaseModel):
    # Section 47's named levers, each independently toggleable so a caller can isolate
    # one factor or run all three together ("or combined").
    interest_rate_shock_bps: float = 100
    vacancy_shock_bps: float = 200
    cap_rate_expansion_bps: float = 100
    apply_rate_shock: bool = True
    apply_vacancy_shock: bool = True
    apply_cap_rate_expansion: bool = True


@router.post("/portfolio/stress-test")
def portfolio_stress_test(
    payload: StressTestRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> dict:
    params = StressParams(
        interest_rate_shock_bps=payload.interest_rate_shock_bps if payload.apply_rate_shock else 0.0,
        vacancy_shock_bps=payload.vacancy_shock_bps if payload.apply_vacancy_shock else 0.0,
        cap_rate_expansion_bps=payload.cap_rate_expansion_bps if payload.apply_cap_rate_expansion else 0.0,
    )
    with db_session(claims_for(user)) as conn:
        return run_portfolio_stress_test(conn, user.org_id, params)


class MilestoneUpdateRequest(BaseModel):
    status: str | None = None
    actual_date: date | None = None
    projected_date: date | None = None
    notes: str | None = None


@router.patch("/deals/{deal_id}/milestones/{milestone_type}")
def update_development_milestone(
    deal_id: str, milestone_type: str, payload: MilestoneUpdateRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select property_address from deals where deal_id = %s", (deal_id,)
            )
            deal = cur.fetchone()
        if deal is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    update development_milestones
                    set status = coalesce(%s, status),
                        actual_date = coalesce(%s, actual_date),
                        projected_date = coalesce(%s, projected_date),
                        notes = coalesce(%s, notes),
                        variance_days = case
                            when coalesce(%s, actual_date) is not null and coalesce(%s, projected_date) is not null
                            then coalesce(%s, actual_date) - coalesce(%s, projected_date)
                            else variance_days
                        end
                    where deal_id = %s and milestone_type = %s
                    returning milestone_id, variance_days
                    """,
                    (payload.status, payload.actual_date, payload.projected_date, payload.notes,
                     payload.actual_date, payload.projected_date, payload.actual_date, payload.projected_date,
                     deal_id, milestone_type),
                )
                milestone = cur.fetchone()
            if milestone is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found")

            spec = milestone_delay_notification(
                property_address=deal["property_address"], milestone_type=milestone_type,
                variance_days=milestone["variance_days"],
            )
            if spec is not None:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "select lp_user_id from deal_lp_access where deal_id = %s", (deal_id,)
                    )
                    lp_user_ids = [row["lp_user_id"] for row in cur.fetchall()]
                for lp_user_id in lp_user_ids:
                    InAppChannel().send(
                        conn, org_id=user.org_id, spec=spec, deal_id=deal_id, recipient_user_id=lp_user_id,
                    )

    return {"deal_id": deal_id, "milestone_type": milestone_type, "variance_days": milestone["variance_days"]}
