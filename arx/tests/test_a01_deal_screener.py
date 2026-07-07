from arx.agents.a01_deal_screener import run_a01
from arx.tests.fakes import FakeModelClient


def _base_response(**overrides) -> dict:
    base = {
        "deal_id": "d1",
        "deal_type_detected": "acquisition",
        "go_no_go": "go",
        "preliminary_cap_rate": 0.06,
        "preliminary_roc": None,
        "in_target_range": True,
        "missing_fields": [],
        "rationale": "Cap rate falls within ZONIQ's 5.5-6.5% target range for this submarket." * 1,
        "routing_recommendation": "route_to_a02",
        "confidence_score": "medium",
        "document_extraction_required": False,
    }
    base.update(overrides)
    return base


def test_run_a01_acquisition_go():
    fake = FakeModelClient(_base_response())
    result = run_a01(
        deal_id="d1", deal_type="acquisition", property_address="123 Main St, Tacoma WA",
        asking_price=5_000_000, unit_count=24, land_area_sf=None, current_gross_rent=500_000,
        intended_use=None, target_cap_rate_range=(0.055, 0.065), target_roc_range=None,
        model_client=fake,
    )
    assert result.output.go_no_go == "go"
    assert result.output.routing_recommendation == "route_to_a02"
    assert result.prompt_version == "1.0.0"


def test_run_a01_no_go_routes_to_end():
    fake = FakeModelClient(_base_response(
        go_no_go="no_go", in_target_range=False, preliminary_cap_rate=0.03,
        routing_recommendation="no_go_end",
        rationale="Cap rate of 3.0% is far below ZONIQ's 5.5-6.5% target range; not pursuing.",
    ))
    result = run_a01(
        deal_id="d1", deal_type="acquisition", property_address="999 Overpriced Ave",
        asking_price=10_000_000, unit_count=24, land_area_sf=None, current_gross_rent=400_000,
        intended_use=None, target_cap_rate_range=(0.055, 0.065), target_roc_range=None,
        model_client=fake,
    )
    assert result.output.go_no_go == "no_go"
    assert result.output.routing_recommendation == "no_go_end"


def test_run_a01_land_deal_routes_to_a10():
    fake = FakeModelClient(_base_response(
        deal_type_detected="land", preliminary_cap_rate=None, preliminary_roc=0.09,
        routing_recommendation="route_to_a10",
    ))
    result = run_a01(
        deal_id="d2", deal_type="land", property_address="Vacant lot, Auburn WA",
        asking_price=800_000, unit_count=None, land_area_sf=40_000, current_gross_rent=None,
        intended_use="multifamily development", target_cap_rate_range=None, target_roc_range=(0.15, 0.20),
        model_client=fake,
    )
    assert result.output.deal_type_detected == "land"
    assert result.output.routing_recommendation == "route_to_a10"


def test_run_a01_sends_target_ranges_to_model():
    fake = FakeModelClient(_base_response())
    run_a01(
        deal_id="d1", deal_type="acquisition", property_address="123 Main St",
        asking_price=5_000_000, unit_count=24, land_area_sf=None, current_gross_rent=500_000,
        intended_use=None, target_cap_rate_range=(0.055, 0.065), target_roc_range=None,
        model_client=fake,
    )
    sent = fake.calls[0]["user_message"]
    assert "0.055" in sent and "0.065" in sent
