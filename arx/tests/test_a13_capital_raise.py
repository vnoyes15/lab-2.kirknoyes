import pytest

from arx.agents.a13_capital_raise import A13ValidationError, run_a13
from arx.tests.fakes import FakeModelClient


def _response(**overrides):
    base = {
        "investor_matches": [
            {"lp_id": "lp-1", "name": "Cascade Family Office", "fit_score": 82,
             "check_size_fit": "Raise target of $1.5M sits comfortably within their $500K-$3M range.",
             "return_expectations_fit": "Target 8% pref aligns with our projected 8.5% cash-on-cash.",
             "asset_type_fit": "Multifamily is their primary focus.",
             "geographic_fit": "PNW secondary markets are their stated geography.",
             "relationship_status": "Invested with us once in 2025; last contact 20 days ago.",
             "recommended_approach": "Warm follow-up referencing the prior deal's performance."},
        ],
        "capital_structure_recommendation": "Raise $1.5M in LP equity structured as a simple LP/GP waterfall with "
                                             "an 8% preferred return and 70/30 promote split above pref, matching "
                                             "the size and risk profile of this deal and this investor base.",
        "track_record_summary": {
            "deals_closed": 2, "total_equity_deployed": 2_400_000,
            "avg_return_vs_projection": 1.03, "strongest_precedent": "Elm Street Apartments, closed 2025, 9.1% actual vs 8.5% projected.",
        },
        "no_track_record_disclosure": None,
    }
    base.update(overrides)
    return base


def test_run_a13_with_track_record():
    fake = FakeModelClient(_response())
    result = run_a13(
        deal_context={"asset_type": "multifamily", "equity_needed": 1_500_000},
        lp_profiles=[{"lp_id": "lp-1", "name": "Cascade Family Office"}],
        org_deal_history={"deals_closed": 2, "total_equity_deployed": 2_400_000,
                           "avg_return_vs_projection": 1.03, "strongest_precedent": "Elm Street Apartments"},
        model_client=fake,
    )
    assert result.output.investor_matches[0].fit_score == 82
    assert result.output.no_track_record_disclosure is None


def test_run_a13_zero_deals_requires_disclosure():
    bad = _response(
        track_record_summary={"deals_closed": 0, "total_equity_deployed": 0,
                               "avg_return_vs_projection": None, "strongest_precedent": None},
        no_track_record_disclosure=None,
    )
    fake = FakeModelClient(bad)
    with pytest.raises(A13ValidationError, match="no_track_record_disclosure"):
        run_a13(
            deal_context={}, lp_profiles=[],
            org_deal_history={"deals_closed": 0, "total_equity_deployed": 0,
                               "avg_return_vs_projection": None, "strongest_precedent": None},
            model_client=fake,
        )


def test_run_a13_zero_deals_with_disclosure_passes():
    response = _response(
        track_record_summary={"deals_closed": 0, "total_equity_deployed": 0,
                               "avg_return_vs_projection": None, "strongest_precedent": None},
        no_track_record_disclosure="ZONIQ has not yet closed a deal on Arx; this raise is supported by "
                                    "underwriting rigor and process quality rather than historical returns.",
    )
    fake = FakeModelClient(response)
    result = run_a13(
        deal_context={}, lp_profiles=[],
        org_deal_history={"deals_closed": 0, "total_equity_deployed": 0,
                           "avg_return_vs_projection": None, "strongest_precedent": None},
        model_client=fake,
    )
    assert result.output.no_track_record_disclosure is not None


def test_run_a13_empty_investor_matches_is_valid():
    response = _response(investor_matches=[])
    fake = FakeModelClient(response)
    result = run_a13(
        deal_context={"asset_type": "industrial"}, lp_profiles=[{"lp_id": "lp-1", "name": "x"}],
        org_deal_history={"deals_closed": 2, "total_equity_deployed": 2_400_000,
                           "avg_return_vs_projection": 1.03, "strongest_precedent": "x"},
        model_client=fake,
    )
    assert result.output.investor_matches == []


def test_run_a13_rejects_short_capital_structure_recommendation():
    bad = _response(capital_structure_recommendation="too short")
    fake = FakeModelClient(bad)
    with pytest.raises(A13ValidationError, match="schema validation"):
        run_a13(
            deal_context={}, lp_profiles=[],
            org_deal_history={"deals_closed": 2, "total_equity_deployed": 1, "avg_return_vs_projection": None, "strongest_precedent": None},
            model_client=fake,
        )
