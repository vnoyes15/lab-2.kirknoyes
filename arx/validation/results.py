"""Shared result type for both validation suites (Section 15).

WHY THIS EXISTS (Section 15): language models are not calculators. A model can return a
DSCR, NOI, and debt service that do not divide correctly. These checks run in Python,
deterministically, after model output and before any database write (Section 10 EH3:
"Validation before every write... Validation failure = always unrecoverable.").
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    check_id: str  # e.g. "MV1", "DV3"
    passed: bool
    message: str
    expected: float | None = None
    actual: float | None = None


class ValidationSuiteResult:
    """Aggregates all checks for one agent output. `passed` is the AND of every check —
    a single failed check makes the whole output unrecoverable (Section 10 EH3)."""

    def __init__(self, results: list[CheckResult]):
        self.results = results

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    def to_dict(self) -> dict:
        # Shape matches error_log.failed_checks (Section 06) for direct insertion when
        # validation fails.
        return {
            "passed": self.passed,
            "checks": [
                {
                    "check_id": r.check_id,
                    "passed": r.passed,
                    "message": r.message,
                    "expected": r.expected,
                    "actual": r.actual,
                }
                for r in self.results
            ],
        }
