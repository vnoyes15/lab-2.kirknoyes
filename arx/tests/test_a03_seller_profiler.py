import pytest

from arx.agents.a03_seller_profiler import A03ValidationError, run_a03
from arx.tests.fakes import FakeModelClient


def _response(**overrides) -> dict:
    base = {
        "seller_archetype": "distressed",
        "distress_indicators": ["tax delinquency filed 2025", "code violation on record"],
        "motivated_seller_score": 78,
        "outreach_approach": "Approach directly and briefly, acknowledging the property's condition without "
                             "dwelling on it; emphasize a fast, as-is closing timeline given the tax lien pressure.",
        "topics_to_avoid": ["Do not reference the tax delinquency directly in first contact."],
        "confidence_score": "medium",
    }
    base.update(overrides)
    return base


def test_run_a03_acquisition_distressed_seller():
    fake = FakeModelClient(_response())
    result = run_a03(
        deal_type="acquisition", property_address="123 Main St, Tacoma WA", owner_name="J. Smith",
        ownership_duration_years=22, public_record_data={"tax_delinquent": True}, model_client=fake,
    )
    assert result.output.seller_archetype == "distressed"
    assert result.output.motivated_seller_score == 78
    assert len(fake.calls) == 1


def test_run_a03_land_archetype():
    fake = FakeModelClient(_response(
        seller_archetype="municipality",
        distress_indicators=[],
        outreach_approach="Engage through the municipality's formal property disposition process rather than "
                          "informal outreach; identify the relevant department contact first.",
        topics_to_avoid=["Avoid informal cash offers outside their public disposition process."],
    ))
    result = run_a03(
        deal_type="land", property_address="Vacant parcel, Auburn WA", owner_name="City of Auburn",
        ownership_duration_years=None, public_record_data={"entity_type": "government"}, model_client=fake,
    )
    assert result.output.seller_archetype == "municipality"
    assert result.output.distress_indicators == []


def test_run_a03_rejects_short_outreach_approach():
    fake = FakeModelClient(_response(outreach_approach="too short"))
    with pytest.raises(A03ValidationError, match="schema validation"):
        run_a03(
            deal_type="acquisition", property_address="123 Main St", owner_name=None,
            ownership_duration_years=None, public_record_data=None, model_client=fake,
        )


def test_run_a03_rejects_empty_topics_to_avoid():
    fake = FakeModelClient(_response(topics_to_avoid=[]))
    with pytest.raises(A03ValidationError):
        run_a03(
            deal_type="acquisition", property_address="123 Main St", owner_name=None,
            ownership_duration_years=None, public_record_data=None, model_client=fake,
        )


def test_run_a03_sends_public_record_data_to_model():
    fake = FakeModelClient(_response())
    run_a03(
        deal_type="acquisition", property_address="123 Main St", owner_name="J. Smith",
        ownership_duration_years=22, public_record_data={"tax_delinquent": True}, model_client=fake,
    )
    assert "tax_delinquent" in fake.calls[0]["user_message"]
