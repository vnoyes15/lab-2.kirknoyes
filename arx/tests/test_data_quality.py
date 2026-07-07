import pytest

from arx.agents.data_quality import a09_correction_rate


def test_correction_rate_none_below_minimum_sample():
    assert a09_correction_rate(["inaccurate", "inaccurate"]) is None


def test_correction_rate_ignores_unflagged_snapshots():
    flags = [None, None, "accurate", "partial", "inaccurate"]
    # only 3 evaluated (non-None) flags, meets the minimum sample
    rate = a09_correction_rate(flags)
    assert rate == pytest.approx(2 / 3)


def test_correction_rate_all_accurate_is_zero():
    assert a09_correction_rate(["accurate", "accurate", "accurate", "accurate"]) == pytest.approx(0.0)


def test_correction_rate_all_inaccurate_is_one():
    assert a09_correction_rate(["inaccurate", "inaccurate", "inaccurate"]) == pytest.approx(1.0)
