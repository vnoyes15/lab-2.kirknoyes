"""Deal Scenario Modeling API — Section 63."""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row
from pydantic import BaseModel

from arx.agents.scenario_modeling import (
    AcquisitionScenarioOverrides,
    DevelopmentScenarioOverrides,
    run_acquisition_scenario,
    run_development_scenario,
)
from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.snapshots import get_active_snapshot

router = APIRouter(prefix="/api/v1/deals/{deal_id}/scenarios", tags=["scenarios"])


class ScenarioRequest(BaseModel):
    scenario_name: str
    track: Literal["acquisition", "development"]
    rent_change_pct: float = 0.0
    vacancy_rate_override: float | None = None
    expense_change_pct: float = 0.0
    interest_rate_override: float | None = None
    construction_cost_overrun_pct: float = 0.0
    exit_cap_rate_override: float | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
def create_scenario(
    deal_id: str, payload: ScenarioRequest,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
) -> dict:
    """Section 63: combined-impact scenario against the deal's active A-02/A-11
    snapshot as baseline. Requires that active snapshot to exist — a scenario is a
    variation on a real underwriting, never a from-scratch guess."""
    with db_session(claims_for(user)) as conn:
        agent_id = "a02" if payload.track == "acquisition" else "a11"
        baseline_snapshot = get_active_snapshot(conn, deal_id=deal_id, agent_id=agent_id)
        if baseline_snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"No active {agent_id} snapshot for this deal — scenario modeling needs a baseline (Section 63)",
            )
        baseline = baseline_snapshot["output_payload"]

        if payload.track == "acquisition":
            output = run_acquisition_scenario(
                baseline=baseline,
                overrides=AcquisitionScenarioOverrides(
                    rent_change_pct=payload.rent_change_pct,
                    vacancy_rate_override=payload.vacancy_rate_override,
                    expense_change_pct=payload.expense_change_pct,
                    interest_rate_override=payload.interest_rate_override,
                ),
            )
        else:
            output = run_development_scenario(
                baseline=baseline,
                overrides=DevelopmentScenarioOverrides(
                    construction_cost_overrun_pct=payload.construction_cost_overrun_pct,
                    rent_change_pct=payload.rent_change_pct,
                    exit_cap_rate_override=payload.exit_cap_rate_override,
                ),
            )

        assumption_overrides = payload.model_dump(exclude={"scenario_name", "track"})
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    insert into scenario_models (deal_id, org_id, scenario_name, assumption_overrides,
                                                  output_payload, created_by_user_id)
                    values (%s, %s, %s, %s, %s, %s)
                    returning scenario_id
                    """,
                    (deal_id, user.org_id, payload.scenario_name,
                     json.dumps(assumption_overrides), json.dumps(output), user.user_id),
                )
                scenario_id = cur.fetchone()["scenario_id"]

    return {"scenario_id": str(scenario_id), "scenario_name": payload.scenario_name, "output": output}


@router.get("")
def list_scenarios(
    deal_id: str, user: CurrentUser = Depends(require_role("admin", "analyst", "viewer")),
) -> list[dict]:
    with db_session(claims_for(user)) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select scenario_id, scenario_name, assumption_overrides, output_payload, created_at "
                "from scenario_models where deal_id = %s order by created_at",
                (deal_id,),
            )
            return cur.fetchall()
