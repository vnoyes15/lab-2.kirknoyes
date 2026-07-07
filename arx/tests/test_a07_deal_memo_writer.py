import pytest

from arx.agents.a07_deal_memo_writer import A07ValidationError, run_a07
from arx.tests.fakes import FakeModelClient

SNAPSHOT = {"cap_rate": 0.06, "noi": 300_000, "dscr": 1.2, "cash_on_cash": 0.04}


def _memo_response(**overrides) -> dict:
    base = {
        "memo_track": "acquisition",
        "sections": {
            "executive_summary": "Solid value-add deal within target cap rate range.",
            "property_overview": "24-unit multifamily in Tacoma, built 1998.",
            "market_context": "Submarket comps support the basis.",
            "investment_thesis": "Below-market rents with clear upside on turnover.",
            "financial_summary": "6.0% cap rate, $300,000 NOI, 1.2x DSCR, 4.0% cash-on-cash.",
            "risk_factors": "x" * 210,
            "deal_structure": "75% LTV acquisition loan, 30-year amortization.",
            "next_steps": "Confirm rent roll during due diligence.",
        },
        "financial_summary_metrics": dict(SNAPSHOT),
        "confidence_disclosure": None,
        "audience_version": "internal",
    }
    base.update(overrides)
    return base


def _run(response, confidence_score="high", **overrides):
    fake = FakeModelClient(response, input_tokens=400, output_tokens=350)
    kwargs = dict(
        memo_track="acquisition", underwriting_snapshot=SNAPSHOT, confidence_score=confidence_score,
        property_context={"address": "123 Main St", "unit_count": 24}, audience_version="internal",
        model_client=fake,
    )
    kwargs.update(overrides)
    return run_a07(**kwargs), fake


def test_run_a07_matching_metrics_passes():
    result, fake = _run(_memo_response())
    assert result.output.memo_track == "acquisition"
    assert len(fake.calls) == 1


def test_run_a07_rejects_mismatched_metric():
    bad = _memo_response(financial_summary_metrics={**SNAPSHOT, "cap_rate": 0.09})
    with pytest.raises(A07ValidationError) as excinfo:
        _run(bad)
    assert excinfo.value.failed_checks["mismatches"][0]["metric"] == "cap_rate"


def test_run_a07_ignores_metrics_not_present_in_snapshot():
    # A development-shaped metric on an acquisition memo isn't a discrepancy to check
    # against — the snapshot simply doesn't have it.
    response = _memo_response(financial_summary_metrics={**SNAPSHOT, "irr": 0.5})
    result, _ = _run(response)
    assert result.output.financial_summary_metrics["irr"] == 0.5


def test_run_a07_low_confidence_requires_disclosure():
    response = _memo_response(confidence_disclosure=None)
    with pytest.raises(A07ValidationError, match="confidence_disclosure"):
        _run(response, confidence_score="low")


def test_run_a07_low_confidence_with_disclosure_passes():
    response = _memo_response(confidence_disclosure="Based on system defaults; no rent roll was provided.")
    result, _ = _run(response, confidence_score="low")
    assert result.output.confidence_disclosure is not None


def test_run_a07_rejects_schema_violation():
    bad = _memo_response()
    bad["sections"]["risk_factors"] = "too short"
    with pytest.raises(A07ValidationError, match="schema validation"):
        _run(bad)
