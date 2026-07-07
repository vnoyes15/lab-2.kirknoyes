"""Notification trigger rules — Section 06 (see arx/db/migrations/027_notifications.sql).

Pure deterministic functions, no AI, no DB — same contract as
arx/agents/momentum_scoring.py and arx/agents/relationship_warmth.py. Each function
takes the facts an event already produced (an A-06 output, a momentum recompute
result, an A-08 rejection) and returns a NotificationSpec dict ready to persist via
arx/db/queries/notifications.py::create_notification, or None if nothing warrants a
notification. Never invents a reason to notify — no output here without a concrete
triggering fact the caller already has in hand.
"""
from dataclasses import dataclass, asdict

MOMENTUM_STALLED_THRESHOLD = 20


@dataclass(frozen=True)
class NotificationSpec:
    notification_type: str
    severity: str
    title: str
    body: str
    source_agent: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def deal_advancement_blocked_notification(
    *, property_address: str, blocking_items: list[dict],
) -> NotificationSpec | None:
    """Fires when A-06 sets deal_advancement_blocked=True (arx/agents/a06_due_diligence.py).
    blocking_items is the subset of checklist_items with status in ('flagged', 'not_started')
    — the same set that drove deal_advancement_blocked True in the first place."""
    if not blocking_items:
        return None

    categories = ", ".join(item["category"] for item in blocking_items)
    return NotificationSpec(
        notification_type="deal_advancement_blocked",
        severity="warning",
        title=f"Due diligence blocked: {property_address}",
        body=f"{len(blocking_items)} due diligence item(s) are blocking advancement: {categories}.",
        source_agent="a06",
    )


def momentum_stalled_notification(
    *, property_address: str, previous_score: int | None, current_score: int | None,
) -> NotificationSpec | None:
    """Fires when a deal's momentum crosses from non-stalled to stalled on a nightly
    recompute (arx/tasks/momentum_scorer.py) — a one-time transition alert, not a
    repeat every night the deal stays stalled (previous_score is compared against
    the threshold too, so once notified, this stays silent until momentum recovers
    and drops again)."""
    if current_score is None or previous_score is None:
        return None
    was_stalled = previous_score < MOMENTUM_STALLED_THRESHOLD
    is_stalled = current_score < MOMENTUM_STALLED_THRESHOLD
    if is_stalled and not was_stalled:
        return NotificationSpec(
            notification_type="momentum_stalled",
            severity="warning",
            title=f"Deal momentum stalled: {property_address}",
            body=f"Momentum score dropped to {current_score} (from {previous_score}) — "
                 f"no recent activity and/or stuck in its current status.",
        )
    return None


def daily_send_limit_reached_notification(*, daily_send_limit: int) -> NotificationSpec:
    """Fires when A-08 raises A08DailyLimitError (arx/agents/a08_outreach.py) — org-wide
    (no specific deal), so the caller passes deal_id=None to create_notification."""
    return NotificationSpec(
        notification_type="daily_send_limit_reached",
        severity="info",
        title="Daily outreach send limit reached",
        body=f"The org's daily outreach send limit of {daily_send_limit} messages has been reached "
             f"for today (Section 22). Further outreach will resume tomorrow.",
        source_agent="a08",
    )
