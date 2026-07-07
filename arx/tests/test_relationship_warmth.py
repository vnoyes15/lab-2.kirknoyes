from datetime import date, datetime, timedelta, timezone

import pytest

from arx.agents.relationship_warmth import compute_warmth

NOW = datetime(2026, 7, 7, tzinfo=timezone.utc)


def test_never_contacted_is_cold():
    assert compute_warmth(None, now=NOW) == "cold"


@pytest.mark.parametrize("days_ago,expected", [
    (0, "hot"), (15, "hot"), (30, "hot"),
    (31, "warm"), (60, "warm"), (90, "warm"),
    (91, "cold"), (365, "cold"),
])
def test_warmth_boundaries_datetime(days_ago, expected):
    contacted = NOW - timedelta(days=days_ago)
    assert compute_warmth(contacted, now=NOW) == expected


def test_warmth_accepts_plain_date():
    contacted = date(2026, 6, 20)  # 17 days before NOW
    assert compute_warmth(contacted, now=NOW) == "hot"


def test_warmth_naive_datetime_treated_as_utc():
    contacted = datetime(2026, 6, 1)  # naive, 36 days before NOW
    assert compute_warmth(contacted, now=NOW) == "warm"


def test_future_contact_date_raises():
    with pytest.raises(ValueError, match="future"):
        compute_warmth(NOW + timedelta(days=1), now=NOW)
