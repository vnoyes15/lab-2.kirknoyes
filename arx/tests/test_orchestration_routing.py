import pytest

from arx.orchestration.routing import (
    has_unresolved_extraction_conflicts,
    needs_document_processing,
    route_after_land_screening,
    route_after_screening,
)


def test_needs_document_processing_true_when_pending():
    assert needs_document_processing({"pending_document_ids": ["doc-1"]})


def test_needs_document_processing_false_when_empty():
    assert not needs_document_processing({"pending_document_ids": []})
    assert not needs_document_processing({})


def test_unresolved_conflicts_detected():
    assert has_unresolved_extraction_conflicts({"document_extraction_conflicts": [{"field": "noi"}]})
    assert not has_unresolved_extraction_conflicts({"document_extraction_conflicts": []})


@pytest.mark.parametrize(
    "deal_type,expected_agent",
    [("acquisition", "a02"), ("land", "a10"), ("development", "a11")],
)
def test_route_after_screening_by_deal_type(deal_type, expected_agent):
    state = {"deal_type": deal_type, "agent_outputs": {"a01": {"go_no_go": "go"}}}
    assert route_after_screening(state) == expected_agent


def test_route_after_screening_no_go_ends():
    state = {"deal_type": "acquisition", "agent_outputs": {"a01": {"go_no_go": "no_go"}}}
    assert route_after_screening(state) == "end"


def test_route_after_screening_requires_a01_output():
    with pytest.raises(ValueError, match="before A-01"):
        route_after_screening({"deal_type": "acquisition", "agent_outputs": {}})


def test_route_after_screening_rejects_unknown_deal_type():
    state = {"deal_type": "condo", "agent_outputs": {"a01": {"go_no_go": "go"}}}
    with pytest.raises(ValueError, match="Unknown or unset deal_type"):
        route_after_screening(state)


def test_route_after_land_screening_pursue_routes_to_a11():
    state = {"agent_outputs": {"a10": {"routing_recommendation": "route_to_a11"}}}
    assert route_after_land_screening(state) == "a11"


def test_route_after_land_screening_pursue_with_profile_routes_to_a03():
    state = {"agent_outputs": {"a10": {"routing_recommendation": "route_to_a03_then_a11"}}}
    assert route_after_land_screening(state) == "a03"


def test_route_after_land_screening_pass_ends():
    state = {"agent_outputs": {"a10": {"routing_recommendation": "pass_end"}}}
    assert route_after_land_screening(state) == "end"
