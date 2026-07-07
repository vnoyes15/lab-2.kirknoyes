"""Deal Risk Monitor persistence/aggregation — Section 44. Pairs with the pure
detection logic in arx/agents/deal_risk_monitor.py the same way notifications.py pairs
with notification_rules.py: this module only gathers facts from the DB and evaluates
them, it never decides on its own what counts as risky.
"""
import psycopg
from psycopg.rows import dict_row

from arx.agents.deal_risk_monitor import (
    RiskFlag,
    cap_rate_repricing_risk,
    construction_budget_variance_risk,
    construction_draw_approaching_limit_risk,
    dd_deadline_with_open_flags_risk,
    dscr_breach_risk,
    schedule_delay_risk,
    seller_distress_escalation_risk,
)

# Section 44: "seller distress escalation post-LOI" — post-LOI acquisition stages.
_POST_LOI_STATUSES = ("loi", "under_contract", "due_diligence")
# Section 44's construction-deal risk set only makes sense once the asset is actually
# under construction or leasing up — not during entitlement, which has its own risk
# profile A-10/A-11 already cover via risk_flags on the A-11 snapshot itself.
_CONSTRUCTION_PHASE_STATUSES = ("construction", "lease_up")


def _acquisition_risk_flags(conn: psycopg.Connection, deal: dict) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select output_payload from deal_snapshots "
            "where deal_id = %s and agent_id = 'a02' and is_active = true",
            (deal["deal_id"],),
        )
        a02 = cur.fetchone()

    if a02 is not None:
        payload = a02["output_payload"]
        flag = dscr_breach_risk(
            dscr_hard_fail=payload["dscr_hard_fail"], dscr_warning=payload["dscr_warning"], dscr=payload["dscr"],
        )
        if flag is not None:
            flags.append(flag)

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select avg(cap_rate) as avg_cap_rate from market_comps where org_id = %s", (deal["org_id"],))
            comps = cur.fetchone()
        if comps is not None and comps["avg_cap_rate"] is not None:
            flag = cap_rate_repricing_risk(
                acquisition_cap_rate=payload["cap_rate"], current_market_cap_rate=float(comps["avg_cap_rate"]),
            )
            if flag is not None:
                flags.append(flag)

    if deal["status"] == "due_diligence":
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select count(*) as cnt from deal_tasks where deal_id = %s and source_agent = 'a06' "
                "and priority = 'high' and status in ('not_started', 'in_progress')",
                (deal["deal_id"],),
            )
            open_flag_count = cur.fetchone()["cnt"]
        flag = dd_deadline_with_open_flags_risk(
            days_in_due_diligence=deal["days_in_current_status"], open_flagged_task_count=open_flag_count,
        )
        if flag is not None:
            flags.append(flag)

    if deal["status"] in _POST_LOI_STATUSES:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select output_payload from deal_snapshots "
                "where deal_id = %s and agent_id = 'a03' and is_active = true",
                (deal["deal_id"],),
            )
            a03 = cur.fetchone()
        if a03 is not None:
            payload = a03["output_payload"]
            flag = seller_distress_escalation_risk(
                motivated_seller_score=payload["motivated_seller_score"],
                distress_indicators=payload["distress_indicators"],
            )
            if flag is not None:
                flags.append(flag)

    return flags


def _construction_risk_flags(conn: psycopg.Connection, deal: dict) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select coalesce(sum(budget_amount), 0) as total_budget, "
            "coalesce(sum(variance_amount), 0) as total_variance, "
            "coalesce(sum(committed_amount), 0) as total_committed, "
            "coalesce(sum(drawn_to_date), 0) as total_drawn "
            "from construction_budget where deal_id = %s",
            (deal["deal_id"],),
        )
        budget = cur.fetchone()

    flag = construction_budget_variance_risk(
        total_budget=float(budget["total_budget"]), total_variance=float(budget["total_variance"]),
    )
    if flag is not None:
        flags.append(flag)

    flag = construction_draw_approaching_limit_risk(
        total_committed=float(budget["total_committed"]), total_drawn=float(budget["total_drawn"]),
    )
    if flag is not None:
        flags.append(flag)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select milestone_type from development_milestones where deal_id = %s and status = 'delayed'",
            (deal["deal_id"],),
        )
        delayed = cur.fetchall()
    flag = schedule_delay_risk(delayed_milestones=delayed)
    if flag is not None:
        flags.append(flag)

    return flags


def evaluate_deal_risk(conn: psycopg.Connection, deal_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, org_id, property_address, deal_type, status, days_in_current_status "
            "from deals where deal_id = %s",
            (deal_id,),
        )
        deal = cur.fetchone()
    if deal is None:
        return None

    if deal["deal_type"] == "acquisition" and deal["status"] not in ("closed", "dead"):
        flags = _acquisition_risk_flags(conn, deal)
    elif deal["deal_type"] in ("land", "development") and deal["status"] in _CONSTRUCTION_PHASE_STATUSES:
        flags = _construction_risk_flags(conn, deal)
    else:
        flags = []

    return {
        "deal_id": deal["deal_id"], "property_address": deal["property_address"],
        "deal_type": deal["deal_type"], "status": deal["status"],
        "risk_flags": [f.to_dict() for f in flags],
    }


def list_org_deal_risk(conn: psycopg.Connection, org_id: str) -> list[dict]:
    """Only deals with at least one active risk flag are returned — same "don't
    surface a wall of nothing" principle as the daily brief's stalled-deal list."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select deal_id from deals where org_id = %s and status not in ('closed', 'dead')", (org_id,))
        deal_ids = [row["deal_id"] for row in cur.fetchall()]
    results = [evaluate_deal_risk(conn, deal_id) for deal_id in deal_ids]
    return [r for r in results if r["risk_flags"]]
