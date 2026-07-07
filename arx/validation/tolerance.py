"""Shared numeric tolerance helper for both validation suites (Section 15)."""


def approx_equal(expected: float, actual: float, rel_tol: float) -> bool:
    if expected == 0:
        return abs(actual) < 1e-9
    return abs(actual - expected) / abs(expected) <= rel_tol
