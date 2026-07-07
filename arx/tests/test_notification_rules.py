from arx.agents.notification_rules import (
    daily_send_limit_reached_notification,
    deal_advancement_blocked_notification,
    momentum_stalled_notification,
)


def test_deal_advancement_blocked_notification_with_no_blocking_items_returns_none():
    assert deal_advancement_blocked_notification(property_address="123 Main St", blocking_items=[]) is None


def test_deal_advancement_blocked_notification_lists_categories():
    spec = deal_advancement_blocked_notification(
        property_address="123 Main St",
        blocking_items=[{"category": "title_and_survey"}, {"category": "environmental_assessment"}],
    )
    assert spec is not None
    assert spec.notification_type == "deal_advancement_blocked"
    assert spec.severity == "warning"
    assert "title_and_survey" in spec.body
    assert "environmental_assessment" in spec.body
    assert spec.source_agent == "a06"


def test_momentum_stalled_notification_fires_on_new_transition():
    spec = momentum_stalled_notification(property_address="123 Main St", previous_score=40, current_score=10)
    assert spec is not None
    assert spec.notification_type == "momentum_stalled"
    assert "10" in spec.body and "40" in spec.body


def test_momentum_stalled_notification_silent_if_already_stalled():
    spec = momentum_stalled_notification(property_address="123 Main St", previous_score=15, current_score=10)
    assert spec is None


def test_momentum_stalled_notification_silent_if_still_healthy():
    spec = momentum_stalled_notification(property_address="123 Main St", previous_score=80, current_score=60)
    assert spec is None


def test_momentum_stalled_notification_handles_missing_previous_score():
    spec = momentum_stalled_notification(property_address="123 Main St", previous_score=None, current_score=10)
    assert spec is None


def test_daily_send_limit_reached_notification_includes_limit():
    spec = daily_send_limit_reached_notification(daily_send_limit=50)
    assert spec.notification_type == "daily_send_limit_reached"
    assert "50" in spec.body
    assert spec.source_agent == "a08"
