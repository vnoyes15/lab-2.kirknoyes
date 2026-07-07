"""Data Quality Engine nightly job — Section 51, Section 86 N8 ("The intelligence
layer runs on Celery Beat"). Runs run_data_quality_checks (arx/db/queries/
data_quality.py) for every org nightly — same superuser-connection shape as
arx/tasks/momentum_scorer.py's "background job, not a per-request path" carve-out.
The report itself is also available on-demand via GET /api/v1/data-quality/report;
this task is what would deliver it automatically once a real notification channel
exists (no email/SMS provider configured — same gap as the rest of this platform's
scheduled-delivery pieces).
"""
import psycopg

from arx.api.config import get_settings
from arx.db.queries.data_quality import run_data_quality_checks
from arx.tasks.celery_app import celery_app


@celery_app.task(name="arx.tasks.run_data_quality_checks_all_orgs")
def run_data_quality_checks_all_orgs() -> dict:
    settings = get_settings()
    reports: dict[str, dict] = {}
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        org_ids = [row[0] for row in conn.execute("select org_id from orgs").fetchall()]
        for org_id in org_ids:
            reports[str(org_id)] = run_data_quality_checks(conn, str(org_id))
    return reports


celery_app.conf.beat_schedule = {
    **celery_app.conf.beat_schedule if celery_app.conf.beat_schedule else {},
    "data-quality-checks-nightly": {
        "task": "arx.tasks.run_data_quality_checks_all_orgs",
        "schedule": 24 * 60 * 60,
    },
}
