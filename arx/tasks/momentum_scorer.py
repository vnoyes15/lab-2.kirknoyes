"""Momentum scoring Celery Beat job — Section 06/23, Section 86 N8 ("The intelligence
layer runs on Celery Beat"). Recomputes deals.momentum_score / days_in_current_status
for every org nightly, using the deterministic logic in arx/agents/momentum_scoring.py
and arx/db/queries/pipeline.py::recalculate_org_momentum — same shape as
relationship_warmth's warmth_score job would take (Section 38; still unwired — see
README's Phase 4 scope-boundary notes).

This task uses a superuser DB connection (DATABASE_URL, not the RLS-bound
APP_DATABASE_URL) deliberately: it iterates every org rather than acting within one
request's tenant scope, which is exactly the "background job, not a per-request path"
case arx/db/connection.py's docstring carves out for bypassing RLS.
"""
import psycopg

from arx.api.config import get_settings
from arx.db.queries.pipeline import recalculate_org_momentum
from arx.notifications.channels import InAppChannel
from arx.tasks.celery_app import celery_app


@celery_app.task(name="arx.tasks.recalculate_all_momentum")
def recalculate_all_momentum() -> dict:
    settings = get_settings()
    channel = InAppChannel()
    updated_by_org: dict[str, int] = {}
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        org_ids = [row[0] for row in conn.execute("select org_id from orgs").fetchall()]
        for org_id in org_ids:
            with conn.transaction():
                updated_by_org[str(org_id)] = recalculate_org_momentum(conn, str(org_id), notify=channel)
    return updated_by_org


celery_app.conf.beat_schedule = {
    **celery_app.conf.beat_schedule if celery_app.conf.beat_schedule else {},
    "recalculate-momentum-nightly": {
        "task": "arx.tasks.recalculate_all_momentum",
        "schedule": 24 * 60 * 60,  # once every 24h; exact time-of-day scheduling is an
                                    # ops concern (crontab), not this module's job to fix.
    },
}
