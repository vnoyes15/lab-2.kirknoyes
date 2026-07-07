#!/usr/bin/env python3
"""Phase 5 Quality Gate runner — Section 14: "All gates pass in one test run on
production before Phase 5 sign-off."

Runs the dedicated test file for each of the 8 gates (G-01 through G-08) and reports
pass/fail per gate, mirroring scripts/run_agent_tests.py's pattern for G-06. G-01,
G-02, G-03, G-04, and G-07 require a reachable DATABASE_URL (they exercise the live
API against live Postgres) and will show as SKIPPED without one; G-05, G-06, and G-08
run regardless. Exits non-zero if any gate fails outright (a SKIP is not a FAIL — see
the note printed for any skipped gate).
"""
import re
import subprocess
import sys

# The real pytest -q summary line always starts with a digit count (e.g. "12 passed,
# 5 warnings in 2.4s" or "3 failed, 9 passed in 1.1s") — matching on that shape, not
# just the substring "passed"/"failed"/"error", avoids false-matching a test file's own
# name (e.g. test_gate_g04_error_contract.py contains the substring "error").
_SUMMARY_LINE_RE = re.compile(r"^\d+ (passed|failed|error|skipped)")

GATE_TEST_FILES = {
    "G-01 (end-to-end)": "arx/tests/test_gate_g01_end_to_end.py",
    "G-02 (org isolation)": "arx/tests/test_gate_g02_org_isolation.py",
    "G-03 (math accuracy)": "arx/tests/test_gate_g03_math_accuracy.py",
    "G-04 (error contract)": "arx/tests/test_gate_g04_error_contract.py",
    "G-05 (versioning)": "arx/tests/test_snapshots_and_quality_log.py",
    "G-06 (test suites)": None,  # special-cased below: delegates to run_agent_tests.py
    "G-07 (token accounting)": "arx/tests/test_gate_g07_token_accounting.py",
    "G-08 (document intelligence)": "arx/tests/test_gate_g08_document_intelligence.py",
}


def _run_pytest(test_file: str) -> tuple[bool, bool, str, subprocess.CompletedProcess]:
    """Returns (passed, skipped_entirely, summary_line, completed_process)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_file, "-q"],
        capture_output=True, text=True,
    )
    summary_line = next(
        (l for l in result.stdout.splitlines() if _SUMMARY_LINE_RE.match(l.strip())),
        "",
    )
    skipped_entirely = "skipped" in summary_line and "passed" not in summary_line
    return result.returncode == 0, skipped_entirely, summary_line.strip(), result


def main() -> int:
    print("Phase 5 Quality Gates (Section 14)\n")

    all_passed = True
    for gate_name, test_file in GATE_TEST_FILES.items():
        if test_file is None:
            # G-06 has its own runner (scripts/run_agent_tests.py) since it reports
            # per-agent, not just pass/fail for one file.
            result = subprocess.run([sys.executable, "scripts/run_agent_tests.py"], capture_output=True, text=True)
            passed = result.returncode == 0
            all_passed = all_passed and passed
            print(f"  [{'PASS' if passed else 'FAIL'}] {gate_name}: see scripts/run_agent_tests.py output below")
            if not passed:
                print(result.stdout)
                print(result.stderr)
            continue

        passed, skipped_entirely, summary, result = _run_pytest(test_file)
        if skipped_entirely:
            print(f"  [SKIP] {gate_name}: {summary} (no reachable DATABASE_URL)")
            continue
        all_passed = all_passed and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {gate_name}: {summary}")
        if not passed:
            print(result.stdout)
            print(result.stderr)

    print("\nOVERALL:", "PASS" if all_passed else "FAIL")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
