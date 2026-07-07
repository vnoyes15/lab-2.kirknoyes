import pytest

from arx.agents.a06_due_diligence import (
    A06ValidationError,
    ACQUISITION_CATEGORIES,
    LAND_DEVELOPMENT_CATEGORIES,
    run_a06,
)
from arx.tests.fakes import FakeModelClient


def _item(category, status="complete", flag_note=None):
    return {
        "item_id": category, "category": category, "description": f"{category} review",
        "why_it_matters": "Standard due diligence for this deal.",
        "responsible_party": "buyer's attorney", "status": status,
        "flag_note": flag_note, "assigned_user_id": None,
    }


def test_run_a06_acquisition_all_complete_not_blocked():
    fake = FakeModelClient({
        "dd_track": "acquisition",
        "checklist_items": [_item(c) for c in ACQUISITION_CATEGORIES],
        "wa_rent_compliance_item": None,
    })
    result = run_a06(dd_track="acquisition", deal_facts={"asset_type": "multifamily"}, model_client=fake)
    assert result.output.deal_advancement_blocked is False
    assert len(result.output.checklist_items) == len(ACQUISITION_CATEGORIES)


def test_run_a06_flagged_item_blocks_advancement():
    items = [_item(c) for c in ACQUISITION_CATEGORIES]
    items[0] = _item(ACQUISITION_CATEGORIES[0], status="flagged", flag_note="Title report shows an unresolved lien from 2019.")
    fake = FakeModelClient({"dd_track": "acquisition", "checklist_items": items, "wa_rent_compliance_item": None})
    result = run_a06(dd_track="acquisition", deal_facts={}, model_client=fake)
    assert result.output.deal_advancement_blocked is True


def test_run_a06_not_started_item_blocks_advancement():
    items = [_item(c) for c in ACQUISITION_CATEGORIES]
    items[-1] = _item(ACQUISITION_CATEGORIES[-1], status="not_started")
    fake = FakeModelClient({"dd_track": "acquisition", "checklist_items": items, "wa_rent_compliance_item": None})
    result = run_a06(dd_track="acquisition", deal_facts={}, model_client=fake)
    assert result.output.deal_advancement_blocked is True


def test_run_a06_wa_multifamily_requires_rent_compliance_item():
    fake = FakeModelClient({
        "dd_track": "acquisition", "checklist_items": [_item(c) for c in ACQUISITION_CATEGORIES],
        "wa_rent_compliance_item": None,
    })
    with pytest.raises(A06ValidationError, match="wa_rent_compliance_item"):
        run_a06(dd_track="acquisition", deal_facts={}, is_wa_multifamily=True, model_client=fake)


def test_run_a06_wa_multifamily_with_rent_compliance_item_passes():
    fake = FakeModelClient({
        "dd_track": "acquisition", "checklist_items": [_item(c) for c in ACQUISITION_CATEGORIES],
        "wa_rent_compliance_item": _item("wa_rent_compliance", status="in_progress"),
    })
    result = run_a06(dd_track="acquisition", deal_facts={}, is_wa_multifamily=True, model_client=fake)
    assert result.output.wa_rent_compliance_item is not None
    # Only "flagged" and "not_started" block advancement (Section 87); "in_progress"
    # does not, same as any other checklist item.
    assert result.output.deal_advancement_blocked is False


def test_run_a06_land_development_track_categories():
    fake = FakeModelClient({
        "dd_track": "land_development",
        "checklist_items": [_item(c) for c in LAND_DEVELOPMENT_CATEGORIES],
        "wa_rent_compliance_item": None,
    })
    result = run_a06(dd_track="land_development", deal_facts={}, model_client=fake)
    assert {item.category for item in result.output.checklist_items} == set(LAND_DEVELOPMENT_CATEGORIES)


def test_run_a06_rejects_missing_category():
    incomplete = [_item(c) for c in ACQUISITION_CATEGORIES[:-1]]  # drop the last required category
    fake = FakeModelClient({"dd_track": "acquisition", "checklist_items": incomplete, "wa_rent_compliance_item": None})
    with pytest.raises(A06ValidationError, match="missing="):
        run_a06(dd_track="acquisition", deal_facts={}, model_client=fake)


def test_run_a06_rejects_unexpected_category():
    items = [_item(c) for c in ACQUISITION_CATEGORIES] + [_item("made_up_category")]
    fake = FakeModelClient({"dd_track": "acquisition", "checklist_items": items, "wa_rent_compliance_item": None})
    with pytest.raises(A06ValidationError, match="unexpected="):
        run_a06(dd_track="acquisition", deal_facts={}, model_client=fake)


def test_run_a06_rejects_flagged_item_without_flag_note():
    items = [_item(c) for c in ACQUISITION_CATEGORIES]
    items[0] = _item(ACQUISITION_CATEGORIES[0], status="flagged", flag_note=None)
    fake = FakeModelClient({"dd_track": "acquisition", "checklist_items": items, "wa_rent_compliance_item": None})
    with pytest.raises(A06ValidationError, match="schema validation"):
        run_a06(dd_track="acquisition", deal_facts={}, model_client=fake)


def test_run_a06_rejects_unknown_track():
    with pytest.raises(ValueError, match="Unknown dd_track"):
        run_a06(dd_track="condo_conversion", deal_facts={}, model_client=FakeModelClient({}))
