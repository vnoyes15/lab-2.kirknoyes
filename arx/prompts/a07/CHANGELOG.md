# a07 prompt changelog

## v1.1.0 — 2026-07-07
Added `financial_summary_metrics` as a distinct structured field, separate from the
prose `sections.financial_summary`. Section 87 requires financial_summary_metrics to
be mechanically checked against the active A-02/A-11 snapshot ("Discrepancies =
unrecoverable error") — that's only checkable against a small structured echo of the
key numbers, not by parsing them back out of free text. v1.0.0 conflated the two.

## v1.0.0 — 2026-07-07
Initial version (Phase 2 build).
