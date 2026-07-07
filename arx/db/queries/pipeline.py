"""Pipeline view + momentum persistence — Section 06/23.

recalculate_org_momentum mirrors arx/db/queries/relationship.py's
recalculate_org_warmth: pure scoring logic lives in arx/agents/momentum_scoring.py,
this module's job is only to gather the per-deal signals from Postgres and persist the
result. Intended to run nightly via Celery Beat (arx/tasks/momentum_scorer.py) — see
that module's docstring for the same "N8 intelligence layer" framing already
established for warmth scoring.
"""
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from arx.agents.momentum_scoring import TERMINAL_STATUSES, compute_momentum_score
from arx.agents.notification_rules import momentum_stalled_notification

# Section 23's per-deal-type status machines, concatenated in advancement order, for
# the pipeline view to group/sort deals into a sensible left-to-right stage order
# regardless of deal_type. Statuses shared across tracks (lead, screened, loi,
# under_contract, due_diligence, entitlement, closed, dead) appear once.
PIPELINE_STAGE_ORDER = [
    "lead", "screened", "feasibility_study", "underwriting", "loi", "under_contract",
    "due_diligence", "entitlement", "construction", "lease_up", "stabilized",
    "closed", "dead",
]


def _last_activity_at(conn: psycopg.Connection, deal_id: str) -> datetime | None:
    row = conn.execute(
        """
        select greatest(
            (select max(created_at) from deal_snapshots where deal_id = %(deal_id)s),
            (select max(sent_at) from outreach_log where deal_id = %(deal_id)s),
            (select max(created_at) from deal_tasks where deal_id = %(deal_id)s),
            (select max(completed_at) from deal_tasks where deal_id = %(deal_id)s)
        ) as last_activity_at
        """,
        {"deal_id": deal_id},
    ).fetchone()
    return row[0] if row else None


def recalculate_org_momentum(
    conn: psycopg.Connection, org_id: str, now: datetime | None = None, notify=None,
) -> int:
    """Recomputes and persists momentum_score and days_in_current_status for every
    non-terminal deal in an org. Returns the number of deals updated.

    notify is an optional arx.notifications.channels.NotificationChannel — when given,
    a deal whose momentum newly crosses into "stalled" this run (see
    arx/agents/notification_rules.py::momentum_stalled_notification) gets a
    notification. Left as None by default so callers (like this module's own tests)
    that only care about the score itself don't need a channel at all."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, property_address, status, status_changed_at, momentum_score "
            "from deals where org_id = %s and status <> all(%s)",
            (org_id, list(TERMINAL_STATUSES)),
        )
        deals = cur.fetchall()

    now = now or datetime.now(timezone.utc)
    for deal in deals:
        days_in_status = (now - deal["status_changed_at"]).days if deal["status_changed_at"] else 0
        last_activity_at = _last_activity_at(conn, deal["deal_id"])
        previous_score = deal["momentum_score"]
        score = compute_momentum_score(
            status=deal["status"], days_in_current_status=days_in_status,
            last_activity_at=last_activity_at, now=now,
        )
        conn.execute(
            "update deals set momentum_score = %s, days_in_current_status = %s where deal_id = %s",
            (score, days_in_status, deal["deal_id"]),
        )

        if notify is not None:
            spec = momentum_stalled_notification(
                property_address=deal["property_address"],
                previous_score=previous_score, current_score=score,
            )
            if spec is not None:
                notify.send(conn, org_id=org_id, spec=spec, deal_id=deal["deal_id"])

    return len(deals)


def get_pipeline_view(
    conn: psycopg.Connection, org_id: str, *,
    status_filter: str | None = None, deal_type: str | None = None,
    assigned_user_id: str | None = None, submarket: str | None = None,
    created_after: str | None = None, created_before: str | None = None,
) -> list[dict]:
    """Returns deals for an org with their current stage and momentum, ordered by
    pipeline stage (Section 23) then by momentum descending within a stage (the deals
    most worth an operator's attention surface first). Section 20: "Dead deals
    excluded by default" — excluded unless status_filter explicitly asks for 'dead'."""
    conditions = ["org_id = %(org_id)s"]
    params: dict = {"org_id": org_id}

    if status_filter is not None:
        conditions.append("status = %(status_filter)s")
        params["status_filter"] = status_filter
    else:
        conditions.append("status <> 'dead'")
    if deal_type is not None:
        conditions.append("deal_type = %(deal_type)s")
        params["deal_type"] = deal_type
    if assigned_user_id is not None:
        conditions.append("assigned_user_id = %(assigned_user_id)s")
        params["assigned_user_id"] = assigned_user_id
    if submarket is not None:
        conditions.append("submarket = %(submarket)s")
        params["submarket"] = submarket
    if created_after is not None:
        conditions.append("created_at >= %(created_after)s")
        params["created_after"] = created_after
    if created_before is not None:
        conditions.append("created_at <= %(created_before)s")
        params["created_before"] = created_before

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            select deal_id, property_address, deal_type, status, asking_price,
                   momentum_score, days_in_current_status, status_changed_at,
                   assigned_user_id, submarket, created_at
            from deals
            where {' and '.join(conditions)}
            """,
            params,
        )
        deals = cur.fetchall()

    def _sort_key(deal: dict) -> tuple:
        stage_index = PIPELINE_STAGE_ORDER.index(deal["status"]) if deal["status"] in PIPELINE_STAGE_ORDER else len(PIPELINE_STAGE_ORDER)
        return (stage_index, -(deal["momentum_score"] or 0))

    return sorted((dict(d) for d in deals), key=_sort_key)


def get_pipeline_analytics(conn: psycopg.Connection, org_id: str) -> dict:
    """Section 20: GET /api/v1/pipeline/analytics — death reason distribution,
    average days per stage, deal type breakdown."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select close_reason_code, count(*) as n from deals "
            "where org_id = %s and status = 'dead' group by close_reason_code",
            (org_id,),
        )
        death_reasons = {row["close_reason_code"]: row["n"] for row in cur.fetchall()}

        cur.execute(
            "select deal_type, count(*) as n from deals where org_id = %s group by deal_type",
            (org_id,),
        )
        deal_type_breakdown = {row["deal_type"]: row["n"] for row in cur.fetchall()}

        # average days per stage: every *closed-out* history entry (exited_at set) has
        # a real duration. Deals still sitting in a stage (exited_at null) aren't
        # counted here — their partial duration would understate the true average of
        # a stage nobody has finished yet.
        cur.execute(
            """
            select status, avg(extract(epoch from (exited_at - entered_at)) / 86400.0) as avg_days
            from deal_status_history
            where org_id = %s and exited_at is not null
            group by status
            """,
            (org_id,),
        )
        avg_days_per_stage = {row["status"]: round(row["avg_days"], 1) for row in cur.fetchall()}

    return {
        "death_reason_distribution": death_reasons,
        "deal_type_breakdown": deal_type_breakdown,
        "average_days_per_stage": avg_days_per_stage,
    }
