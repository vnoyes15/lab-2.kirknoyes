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

PATCH /{deal_id}/status — Section 23: "Each stage transition requires timestamp and
user." Nothing before Phase 5 ever transitioned a deal's status at all (deals were
created and left at 'lead' forever); this is the first place deal_status_history
(arx/db/migrations/029_deal_status_history.sql) gets written, which Section 20's
pipeline analytics ("average days per stage") depends on.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import errors as psycopg_errors
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from arx.agents.notification_rules import task_assigned_notification
from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.notifications.channels import InAppChannel

router = APIRouter(prefix="/api/v1/deals", tags=["deals"])
TASK_PRIORITIES = ("low", "medium", "high")

DealType = Literal["acquisition", "land", "development"]
DEAL_STATUSES = (
    "lead", "screened", "feasibility_study", "underwriting", "loi", "under_contract",
    "due_diligence", "entitlement", "construction", "lease_up", "stabilized", "closed", "dead",
)
CLOSE_REASON_CODES = (
    "seller_declined_offer", "deal_failed_underwriting", "financing_unavailable",
    "due_diligence_failed", "entitlement_failed", "construction_cost_infeasible", "other",
)


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

    with db_session(claims_for(user)) as conn:
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
                    cur.execute(
                        "insert into deal_status_history (deal_id, org_id, status, changed_by_user_id) "
                        "values (%s, %s, 'lead', %s)",
                        (row["deal_id"], user.org_id, user.user_id),
                    )
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


class DealStatusUpdateRequest(BaseModel):
    status: Literal[DEAL_STATUSES]
    close_reason_code: Literal[CLOSE_REASON_CODES] | None = None


@router.patch("/{deal_id}/status")
def update_deal_status(
    deal_id: str, payload: DealStatusUpdateRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    if payload.status == "dead" and payload.close_reason_code is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="close_reason_code is required when status is 'dead' (Section 23)",
        )

    with db_session(claims_for(user)) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select status from deals where deal_id = %s", (deal_id,))
            deal = cur.fetchone()
        if deal is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

        if payload.status == "closed":
            # Section 73: "A deal cannot advance from due_diligence to closed while
            # any task with priority = high has status = not_started or in_progress.
            # Enforced at the API layer — not a UI suggestion." Nothing before Phase 6
            # ever enforced this despite deal_tasks/status existing since Phase 2/4.
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "select task_id, title from deal_tasks where deal_id = %s and priority = 'high' "
                    "and status in ('not_started', 'in_progress')",
                    (deal_id,),
                )
                blocking_tasks = cur.fetchall()
            if blocking_tasks:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": "Deal cannot advance to closed while high-priority tasks are open (Section 73)",
                        "blocking_tasks": [{"task_id": str(t["task_id"]), "title": t["title"]} for t in blocking_tasks],
                    },
                )

        with conn.transaction():
            conn.execute(
                "update deal_status_history set exited_at = now() "
                "where deal_id = %s and exited_at is null",
                (deal_id,),
            )
            conn.execute(
                "update deals set status = %s, close_reason_code = %s where deal_id = %s",
                (payload.status, payload.close_reason_code, deal_id),
            )
            conn.execute(
                "insert into deal_status_history (deal_id, org_id, status, changed_by_user_id) "
                "values (%s, %s, %s, %s)",
                (deal_id, user.org_id, payload.status, user.user_id),
            )

    return {"deal_id": deal_id, "status": payload.status}


@router.get("/{deal_id}")
def get_deal(deal_id: str, user: CurrentUser = Depends(require_role("admin", "analyst", "viewer"))):
    with db_session(claims_for(user)) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select * from deals where deal_id = %s", (deal_id,))
            row = cur.fetchone()
    if row is None:
        # RLS means this also fires for another org's deal_id — indistinguishable from
        # "does not exist" by design (MT4: zero cross-org leakage, including via error
        # message differences).
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    return row


class DealTaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None
    due_date: str | None = None
    assigned_to_user_id: str | None = None
    priority: Literal[TASK_PRIORITIES] = "medium"


@router.post("/{deal_id}/tasks", status_code=status.HTTP_201_CREATED)
def create_deal_task(
    deal_id: str, payload: DealTaskCreateRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    with db_session(claims_for(user)) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select deal_id, property_address from deals where deal_id = %s", (deal_id,))
            deal = cur.fetchone()
        if deal is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

        with conn.transaction():
            row = conn.execute(
                """
                insert into deal_tasks (deal_id, org_id, title, description, due_date,
                                         assigned_to_user_id, priority, source_agent)
                values (%s, %s, %s, %s, %s, %s, %s, null)
                returning task_id
                """,
                (deal_id, user.org_id, payload.title, payload.description, payload.due_date,
                 payload.assigned_to_user_id, payload.priority),
            ).fetchone()
            task_id = str(row[0])

            # Section 73: "Assigned users receive notification on task creation." Manually
            # created tasks may be left unassigned (assigned_to_user_id is nullable), in
            # which case there's no one to notify yet.
            if payload.assigned_to_user_id is not None:
                spec = task_assigned_notification(
                    title=payload.title, property_address=deal["property_address"], source_agent=None,
                )
                InAppChannel().send(
                    conn, org_id=user.org_id, spec=spec, deal_id=deal_id,
                    recipient_user_id=payload.assigned_to_user_id,
                )

    return {"task_id": task_id, "deal_id": deal_id, "status": "not_started"}


@router.get("/{deal_id}/tasks")
def list_deal_tasks(
    deal_id: str, user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select deal_id from deals where deal_id = %s", (deal_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
            cur.execute(
                "select * from deal_tasks where deal_id = %s order by created_at desc", (deal_id,),
            )
            return cur.fetchall()
