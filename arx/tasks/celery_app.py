"""Celery application instance — Section 05 tech stack ("Task queue: Redis + Celery +
Celery Beat"), Section 86 N8 ("The intelligence layer runs on Celery Beat").

The actual intelligence jobs (daily_brief.py, momentum_scorer.py, warmth_scorer.py,
market_signals.py, data_quality.py, feedback_loop.py — Section 86 repo structure) are
Phase 4+ work (N8's jobs all depend on agents that don't exist until Phase 2/3). This
module wires the Celery app itself now, against REDIS_URL, so those task modules have
somewhere real to register against without a Phase 4 infrastructure migration.
"""
from celery import Celery

from arx.api.config import get_settings

settings = get_settings()

celery_app = Celery("arx", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task(name="arx.tasks.healthcheck")
def healthcheck() -> str:
    return "ok"
