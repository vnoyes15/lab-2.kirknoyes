"""Deal momentum scoring — Section 06/23. deals.momentum_score (0-100, nullable) and
deals.days_in_current_status were both provisioned back in Phase 1
(arx/db/migrations/005_deals.sql) but nothing populated them until now — same
"columns land in Phase 1, logic lands when its dependencies exist" shape as
relationship_warmth.py's warmth_score for contacts (Section 38).

Pure deterministic function, no AI — same contract as arx/agents/relationship_warmth.py
and arx/validation/*: never fabricate a number the platform can compute for itself.

Momentum answers "is this deal moving, or has it stalled?" It combines two signals:
  1. Recency of real activity on the deal — any agent snapshot, any outreach sent, any
     deal_task created or completed. The single most recent of these timestamps is
     "last_activity_at"; the fewer days since then, the higher the score.
  2. How long the deal has sat in its current pipeline status (days_in_current_status,
     from deals.status_changed_at — see arx/db/migrations/026_deal_status_changed_at.sql).
     A deal can have fresh activity but still be stuck (e.g. daily back-and-forth on an
     LOI that never gets signed) — the status-duration penalty catches that.

Terminal statuses ('closed', 'dead') return None rather than a number: a finished deal
has no momentum to speak of, and reporting a stale/decaying score for it would be
exactly the kind of fabricated-looking-but-meaningless number N3 prohibits.

Thresholds below are a ZONIQ operating-cadence assumption (a deal an operator hasn't
touched in 2+ weeks is going cold; 30+ days stuck in one status is a real stall) — not
pulled from a spec section that names exact day counts, so they're documented here
rather than presented as a hard requirement.
"""
from datetime import date, datetime, timezone

TERMINAL_STATUSES = ("closed", "dead")

_RECENCY_BREAKPOINTS = ((3, 100), (7, 80), (14, 60), (30, 35), (60, 15))
_STATUS_DURATION_PENALTIES = ((14, 0), (30, 10), (60, 25))
_STATUS_DURATION_MAX_PENALTY = 40


def _days_since(ts: datetime | date | None, now: datetime) -> int | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)
    days = (now - ts).days
    if days < 0:
        raise ValueError("Timestamp is in the future")
    return days


def _recency_score(days_since_last_activity: int | None) -> int:
    if days_since_last_activity is None:
        return 0
    for threshold, score in _RECENCY_BREAKPOINTS:
        if days_since_last_activity <= threshold:
            return score
    return 0


def _status_duration_penalty(days_in_current_status: int) -> int:
    for threshold, penalty in _STATUS_DURATION_PENALTIES:
        if days_in_current_status <= threshold:
            return penalty
    return _STATUS_DURATION_MAX_PENALTY


def compute_momentum_score(
    *,
    status: str,
    days_in_current_status: int,
    last_activity_at: datetime | date | None,
    now: datetime | None = None,
) -> int | None:
    """last_activity_at is the most recent of: last deal_snapshot.created_at, last
    outreach_log.sent_at, last deal_tasks.created_at/completed_at for this deal — the
    caller (arx/db/queries/pipeline.py) is responsible for computing that max across
    tables; this function only turns it into a score."""
    if status in TERMINAL_STATUSES:
        return None
    if days_in_current_status < 0:
        raise ValueError("days_in_current_status cannot be negative")

    now = now or datetime.now(timezone.utc)
    days_since_activity = _days_since(last_activity_at, now)

    score = _recency_score(days_since_activity) - _status_duration_penalty(days_in_current_status)
    return max(0, min(100, score))
