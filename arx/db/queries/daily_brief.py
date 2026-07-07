"""Daily Intelligence Brief — Section 40.

"Deal activity summary. Stalled deal alerts. DD countdowns. Development milestone
status. Top 3 new leads. Market pulse per submarket. Relationship warmth alerts.
Blocked tasks. Construction budget variance. Recommended next action per active deal.
Personalized per user — Analyst sees assigned deals, Admin sees full org picture."

This module builds the brief's *content* deterministically from data already in
Postgres — no AI call, matching arx/agents/momentum_scoring.py's contract. The 6am
scheduled multi-channel delivery Section 40 describes is deferred (no email/SMS
provider — same gap as arx/notifications/channels.py); this is the on-demand data an
operator (or, later, a Celery Beat job) reads to actually build that delivery.

Two things Section 40 asks for have no underlying model anywhere in the platform, so
they're approximated and documented rather than fabricated:
  - "DD countdowns" — no deal-level DD-deadline field exists (only org-configurable DD
    period defaults per Section 56). Approximated as days_in_current_status for deals
    currently in 'due_diligence'.
  - "Top 3 new leads" — Section 36's motivated-seller-score lead queue is Phase 6+
    automation; approximated as the 3 most recently created status='lead' deals.

Section 51's "missing required fields for next stage surface in daily brief as
deal-specific action items" and Section 76 FL2's "Arx prompts for monthly actuals in
the daily brief on the 5th of each month for all owned assets" are both folded in
here rather than left as separate reports nobody actually looks at.
"""
from datetime import date

import psycopg
from psycopg.rows import dict_row

from arx.agents.notification_rules import MOMENTUM_STALLED_THRESHOLD
from arx.db.queries.data_quality import get_missing_required_fields_action_items

# Section 76 FL2: "on the 5th of each month" — the daily brief only carries the
# monthly-actuals prompt on that one day, not every day of the month.
MONTHLY_ACTUALS_PROMPT_DAY = 5


def build_daily_brief(
    conn: psycopg.Connection, *, org_id: str, user_id: str, role: str, today: date | None = None,
) -> dict:
    today = today or date.today()
    deal_scope_sql = "org_id = %(org_id)s"
    params = {"org_id": org_id, "user_id": user_id}
    if role != "admin":
        deal_scope_sql += " and assigned_user_id = %(user_id)s"

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"select deal_id, property_address, status, momentum_score, days_in_current_status, deal_type "
            f"from deals where {deal_scope_sql} and status not in ('closed', 'dead')",
            params,
        )
        active_deals = cur.fetchall()

        cur.execute(
            f"select count(*) as n from deals where {deal_scope_sql} "
            f"and deal_id in (select deal_id from deal_snapshots where created_at >= now() - interval '24 hours')",
            params,
        )
        deal_activity_count = cur.fetchone()["n"]

        cur.execute(
            "select deal_id, property_address, created_at from deals "
            "where org_id = %(org_id)s and status = 'lead' order by created_at desc limit 3",
            {"org_id": org_id},
        )
        top_new_leads = cur.fetchall()

        cur.execute(
            "select contact_id, name, last_contacted_at from contacts "
            "where org_id = %(org_id)s and warmth_score = 'cold' order by last_contacted_at nulls first limit 10",
            {"org_id": org_id},
        )
        relationship_warmth_alerts = cur.fetchall()

        cur.execute(
            "select submarket, avg(cap_rate) as avg_cap_rate, count(*) as n_comps "
            "from market_comps where org_id = %(org_id)s and sale_date >= current_date - interval '180 days' "
            "group by submarket",
            {"org_id": org_id},
        )
        market_pulse = cur.fetchall()

        deal_ids = [d["deal_id"] for d in active_deals]
        blocked_tasks = []
        if deal_ids:
            cur.execute(
                "select task_id, deal_id, title, priority from deal_tasks "
                "where deal_id = any(%s) and status = 'blocked'",
                (deal_ids,),
            )
            blocked_tasks = cur.fetchall()

            cur.execute(
                "select deal_id, milestone_type, projected_date, status, variance_days "
                "from development_milestones where deal_id = any(%s)",
                (deal_ids,),
            )
            development_milestone_status = cur.fetchall()

            cur.execute(
                "select deal_id, coalesce(sum(variance_amount), 0) as total_variance "
                "from construction_budget where deal_id = any(%s) group by deal_id",
                (deal_ids,),
            )
            construction_budget_variance = cur.fetchall()
        else:
            development_milestone_status = []
            construction_budget_variance = []

        monthly_actuals_prompt = []
        if today.day == MONTHLY_ACTUALS_PROMPT_DAY:
            cur.execute(
                "select deal_id, property_address from deals "
                "where org_id = %(org_id)s and is_acquired = true "
                "and deal_id not in ("
                "  select deal_id from deal_performance "
                "  where period >= date_trunc('month', %(today)s::date - interval '1 month')"
                ")",
                {"org_id": org_id, "today": today},
            )
            monthly_actuals_prompt = cur.fetchall()

    stalled_deals = [d for d in active_deals if (d["momentum_score"] or 0) < MOMENTUM_STALLED_THRESHOLD]
    dd_countdowns = [
        {"deal_id": d["deal_id"], "property_address": d["property_address"],
         "days_in_due_diligence": d["days_in_current_status"]}
        for d in active_deals if d["status"] == "due_diligence"
    ]
    blocked_by_deal: dict[str, int] = {}
    for task in blocked_tasks:
        blocked_by_deal[task["deal_id"]] = blocked_by_deal.get(task["deal_id"], 0) + 1

    recommended_next_actions = []
    for deal in active_deals:
        action = _recommend_next_action(
            deal, is_stalled=deal in stalled_deals, blocked_task_count=blocked_by_deal.get(deal["deal_id"], 0),
        )
        if action is not None:
            recommended_next_actions.append({"deal_id": deal["deal_id"], "recommendation": action})

    missing_required_fields_action_items = get_missing_required_fields_action_items(conn, org_id)
    if role != "admin":
        deal_id_set = set(deal_ids)
        missing_required_fields_action_items = [
            item for item in missing_required_fields_action_items if item["deal_id"] in deal_id_set
        ]

    return {
        "deal_activity_summary": {"deals_with_activity_last_24h": deal_activity_count, "total_active_deals": len(active_deals)},
        "stalled_deal_alerts": stalled_deals,
        "dd_countdowns": dd_countdowns,
        "development_milestone_status": development_milestone_status,
        "top_new_leads": top_new_leads,
        "market_pulse": market_pulse,
        "relationship_warmth_alerts": relationship_warmth_alerts,
        "blocked_tasks": blocked_tasks,
        "construction_budget_variance": construction_budget_variance,
        "recommended_next_actions": recommended_next_actions,
        "data_quality_action_items": missing_required_fields_action_items,
        "monthly_actuals_prompt": monthly_actuals_prompt,
    }


def _recommend_next_action(deal: dict, *, is_stalled: bool, blocked_task_count: int) -> str | None:
    """Deterministic, rule-based — not a 14th AI agent. Priority order: a blocked task
    is the most concrete, actionable signal; a stalled deal is next; otherwise no
    specific recommendation (silence is correct when nothing is actually wrong)."""
    if blocked_task_count > 0:
        return f"{blocked_task_count} task(s) blocked — resolve before this deal can advance."
    if is_stalled:
        return "No recent activity and/or stuck in its current status — check in on this deal."
    return None
