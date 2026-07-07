"""Data Quality Engine — Section 51.

"Nightly job checks: market_comps older than 90 days, lender_profiles older than 12
months, market_intelligence older than 60 days, active deal snapshots where source
data was entered more than 30 days ago, A-09 extraction records with high correction
rates. Missing required fields for next stage surface in daily brief as deal-specific
action items."

market_intelligence is not implemented here: no such table exists anywhere in this
schema (checked across every migration) — there's no other section that defines what
it would contain distinct from market_comps/market_signals, so rather than inventing
a table and a staleness check for data that was never actually modeled, this is a
documented gap surfaced explicitly in the report (see
arx/db/queries/data_quality.py::run_data_quality_checks), not silently dropped.

Only the A-09 "high correction rate" check needs real logic beyond a date-threshold
comparison — the rest are simple age-vs-threshold SQL filters in the DB layer. This
module holds the thresholds (so tests and the DB layer share one source of truth) and
the one non-trivial computation.
"""
MARKET_COMPS_STALE_DAYS = 90
LENDER_PROFILES_STALE_DAYS = 365  # "12 months"
ACTIVE_SNAPSHOT_STALE_DAYS = 30

# No exact percentage is given in the spec for "high correction rate" — 20% is a
# ZONIQ operating-cadence assumption, same category as this codebase's other
# documented thresholds (momentum_scoring.py, notification_rules.py).
A09_CORRECTION_RATE_THRESHOLD = 0.20
# Below this many evaluated (accuracy-flagged) snapshots, a rate isn't meaningful —
# one inaccurate flag out of one snapshot is a 100% "rate" that says nothing.
A09_CORRECTION_RATE_MIN_SAMPLE = 3


def a09_correction_rate(accuracy_flags: list[str | None]) -> float | None:
    """accuracy_flags is every a09 deal_snapshots.accuracy_flag value for one agent
    (or however the caller scopes the sample) within the lookback window. Returns
    None when the sample is too small to draw a conclusion from, rather than a
    misleadingly precise rate."""
    evaluated = [f for f in accuracy_flags if f is not None]
    if len(evaluated) < A09_CORRECTION_RATE_MIN_SAMPLE:
        return None
    corrections = sum(1 for f in evaluated if f in ("partial", "inaccurate"))
    return corrections / len(evaluated)
