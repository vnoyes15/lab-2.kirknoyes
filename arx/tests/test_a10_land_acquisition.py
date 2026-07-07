import pytest

from arx.agents.a10_land_acquisition import A10ValidationError, run_a10
from arx.tests.fakes import FakeModelClient


def _response(**overrides):
    base = {
        "feasibility_recommendation": "pursue",
        "entitlement_path": "by_right",
        "site_risk_flags": [],
        "seller_archetype": "long_hold",
        "routing_recommendation": "route_to_a11",
        "confidence_score": "medium",
        "estimated_developable_units": 32,
        "estimated_land_cost_per_unit": 25_000,
        "entitlement_timeline_estimate_months": 4,
        "land_cost_benchmark_comparison": "In line with the org's $25,000/unit benchmark for this submarket.",
    }
    base.update(overrides)
    return base


def test_run_a10_by_right_pursue():
    fake = FakeModelClient(_response())
    result = run_a10(
        property_address="Vacant lot, Auburn WA", land_area_sf=40_000, asking_price=800_000,
        intended_use="multifamily", zoning_info={"zone": "R-3", "by_right": True},
        site_info=None, owner_name="J. Doe", ownership_duration_years=30, entity_type="individual",
        org_land_cost_per_unit_benchmark=25_000, model_client=fake,
    )
    assert result.output.feasibility_recommendation == "pursue"
    assert result.output.entitlement_path == "by_right"
    assert result.output.routing_recommendation == "route_to_a11"


def test_run_a10_rezoning_required_flagged():
    fake = FakeModelClient(_response(
        feasibility_recommendation="conditional_pursue", entitlement_path="rezoning_required",
        site_risk_flags=["political_entitlement_risk"], routing_recommendation="route_to_a03_then_a11",
        estimated_developable_units=None, estimated_land_cost_per_unit=None,
        land_cost_benchmark_comparison=None,
    ))
    result = run_a10(
        property_address="Parcel B, Kent WA", land_area_sf=60_000, asking_price=1_200_000,
        intended_use="multifamily", zoning_info={"zone": "industrial"}, site_info=None,
        owner_name=None, ownership_duration_years=None, entity_type=None, model_client=fake,
    )
    assert result.output.entitlement_path == "rezoning_required"
    assert "political_entitlement_risk" in result.output.site_risk_flags


def test_run_a10_municipality_seller_pass_end():
    fake = FakeModelClient(_response(
        feasibility_recommendation="pass", seller_archetype="municipality",
        routing_recommendation="pass_end", site_risk_flags=["utility_availability_unknown"],
    ))
    result = run_a10(
        property_address="City-owned parcel", land_area_sf=20_000, asking_price=None,
        intended_use="multifamily", zoning_info=None, site_info=None,
        owner_name="City of Kent", ownership_duration_years=None, entity_type="government",
        model_client=fake,
    )
    assert result.output.routing_recommendation == "pass_end"


def test_run_a10_rejects_bad_entitlement_path():
    bad = _response(entitlement_path="probably_fine")
    fake = FakeModelClient(bad)
    with pytest.raises(A10ValidationError, match="schema validation"):
        run_a10(
            property_address="x", land_area_sf=None, asking_price=None, intended_use=None,
            zoning_info=None, site_info=None, owner_name=None, ownership_duration_years=None,
            entity_type=None, model_client=fake,
        )


def test_run_a10_sends_benchmark_to_model():
    fake = FakeModelClient(_response())
    run_a10(
        property_address="x", land_area_sf=40_000, asking_price=800_000, intended_use="multifamily",
        zoning_info=None, site_info=None, owner_name=None, ownership_duration_years=None,
        entity_type=None, org_land_cost_per_unit_benchmark=25_000, model_client=fake,
    )
    assert "25000" in fake.calls[0]["user_message"] or "25_000" in fake.calls[0]["user_message"]
