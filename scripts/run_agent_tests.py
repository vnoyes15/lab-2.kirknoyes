#!/usr/bin/env python3
"""Agent test runner — a phase-scoped version of Gate G-06 ("All 13 agents pass
synthetic test suites at 100% via test runner script").

9 of the 13 agents exist so far (A-01, A-02, A-07, A-09 — Phase 2; A-03, A-04, A-05,
A-12, A-13 — Phase 3, Section 07). This runs exactly their synthetic test suites and
reports pass/fail per agent, so the gate can be checked incrementally as each agent
lands rather than only at the very end of Phase 5. Exits non-zero if any agent's suite
doesn't pass at 100%.
"""
import subprocess
import sys

AGENT_TEST_FILES = {
    "a01": "arx/tests/test_a01_deal_screener.py",
    "a02": "arx/tests/test_a02_underwriting_agent.py",
    "a03": "arx/tests/test_a03_seller_profiler.py",
    "a04": "arx/tests/test_a04_offer_strategy.py",
    "a05": "arx/tests/test_a05_loi_drafting.py",
    "a07": "arx/tests/test_a07_deal_memo_writer.py",
    "a09": "arx/tests/test_a09_document_intelligence.py",
    "a12": "arx/tests/test_a12_negotiation_support.py",
    "a13": "arx/tests/test_a13_capital_raise.py",
}

NOT_YET_BUILT = ["a06", "a08", "a10", "a11"]


def main() -> int:
    print(f"Gate G-06 ({len(AGENT_TEST_FILES)}/13 agents built)\n")

    all_passed = True
    for agent_id, test_file in AGENT_TEST_FILES.items():
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-q"],
            capture_output=True, text=True,
        )
        passed = result.returncode == 0
        all_passed = all_passed and passed
        summary_line = next((l for l in result.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l), "")
        print(f"  [{'PASS' if passed else 'FAIL'}] {agent_id}: {summary_line.strip()}")
        if not passed:
            print(result.stdout)
            print(result.stderr)

    print(f"\nNot yet built (later phases per Section 07): {', '.join(NOT_YET_BUILT)}")
    print("\nOVERALL:", "PASS" if all_passed else "FAIL")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
