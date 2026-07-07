"""Relationship warmth scoring — Section 38.

"Every contact has a warmth_score: hot (contacted within 30 days), warm (31-90 days),
cold (91+ days). Recalculated nightly from outreach_log recency and deal activity."

Pure deterministic function, no AI — same contract as arx/validation/* and
arx/agents/loan_math.py. Section 38's "outreach_log recency" input isn't available yet
(outreach_log is written by A-08, which lands in Phase 4) — this Phase 3 version scores
purely off contacts.last_contacted_at, which the Phase 4 Celery Beat job (N8) will keep
current from outreach_log once A-08 exists. Never contacted at all (last_contacted_at
is None) is treated as cold, not an error — an unreached contact has no warmth yet.
"""
from datetime import date, datetime, timezone

HOT_WITHIN_DAYS = 30
WARM_WITHIN_DAYS = 90

Warmth = str  # "hot" | "warm" | "cold"


def compute_warmth(last_contacted_at: datetime | date | None, now: datetime | None = None) -> Warmth:
    if last_contacted_at is None:
        return "cold"

    now = now or datetime.now(timezone.utc)
    if isinstance(last_contacted_at, datetime):
        contacted = last_contacted_at
        if contacted.tzinfo is None:
            contacted = contacted.replace(tzinfo=timezone.utc)
    else:
        contacted = datetime(last_contacted_at.year, last_contacted_at.month, last_contacted_at.day, tzinfo=timezone.utc)

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    days_since_contact = (now - contacted).days
    if days_since_contact < 0:
        raise ValueError("last_contacted_at is in the future")

    if days_since_contact <= HOT_WITHIN_DAYS:
        return "hot"
    if days_since_contact <= WARM_WITHIN_DAYS:
        return "warm"
    return "cold"
