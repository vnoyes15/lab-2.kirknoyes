from datetime import datetime, timedelta, timezone

import pytest

from arx.agents.momentum_scoring import compute_momentum_score

NOW = datetime(2026, 7, 7, tzinfo=timezone.utc)


def test_terminal_status_returns_none():
    assert compute_momentum_score(
        status="closed", days_in_current_status=5, last_activity_at=NOW, now=NOW
    ) is None
    assert compute_momentum_score(
        status="dead", days_in_current_status=5, last_activity_at=NOW, now=NOW
    ) is None


def test_fresh_activity_and_new_status_scores_high():
    score = compute_momentum_score(
        status="underwriting", days_in_current_status=1,
        last_activity_at=NOW - timedelta(days=1), now=NOW,
    )
    assert score == 100


def test_never_any_activity_scores_zero():
    score = compute_momentum_score(
        status="lead", days_in_current_status=0, last_activity_at=None, now=NOW,
    )
    assert score == 0


def test_stale_activity_scores_low():
    score = compute_momentum_score(
        status="loi", days_in_current_status=5,
        last_activity_at=NOW - timedelta(days=90), now=NOW,
    )
    assert score == 0


def test_long_status_duration_penalizes_even_with_fresh_activity():
    fresh = compute_momentum_score(
        status="due_diligence", days_in_current_status=1,
        last_activity_at=NOW - timedelta(days=1), now=NOW,
    )
    stuck = compute_momentum_score(
        status="due_diligence", days_in_current_status=75,
        last_activity_at=NOW - timedelta(days=1), now=NOW,
    )
    assert stuck < fresh


def test_negative_days_in_status_rejected():
    with pytest.raises(ValueError):
        compute_momentum_score(status="lead", days_in_current_status=-1, last_activity_at=None, now=NOW)


def test_future_activity_timestamp_rejected():
    with pytest.raises(ValueError):
        compute_momentum_score(
            status="lead", days_in_current_status=0,
            last_activity_at=NOW + timedelta(days=1), now=NOW,
        )


def test_score_never_below_zero_or_above_100():
    for days_status in (0, 5, 20, 40, 80, 400):
        for days_activity in (0, 5, 20, 40, 80, 400, None):
            last_activity = None if days_activity is None else NOW - timedelta(days=days_activity)
            score = compute_momentum_score(
                status="screened", days_in_current_status=days_status,
                last_activity_at=last_activity, now=NOW,
            )
            assert 0 <= score <= 100
