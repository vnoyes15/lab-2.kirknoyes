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


def get_pipeline_view(conn: psycopg.Connection, org_id: str) -> list[dict]:
    """Returns every non-dead deal for an org with its current stage and momentum,
    ordered by pipeline stage (Section 23) then by momentum descending within a stage
    (the deals most worth an operator's attention surface first)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select deal_id, property_address, deal_type, status, asking_price,
                   momentum_score, days_in_current_status, status_changed_at
            from deals
            where org_id = %s and status <> 'dead'
            """,
            (org_id,),
        )
        deals = cur.fetchall()

    def _sort_key(deal: dict) -> tuple:
        stage_index = PIPELINE_STAGE_ORDER.index(deal["status"]) if deal["status"] in PIPELINE_STAGE_ORDER else len(PIPELINE_STAGE_ORDER)
        return (stage_index, -(deal["momentum_score"] or 0))

    return sorted((dict(d) for d in deals), key=_sort_key)
