import pytest

from arx.agents.a05_loi_drafting import A05ValidationError, run_a05
from arx.tests.fakes import FakeModelClient

WA_JURISDICTION = {
    "state_code": "WA", "earnest_money_pct": 0.01, "earnest_money_holder": "licensed_escrow",
    "acquisition_dd_days": 30, "rent_control_active": True,
    "rent_control_cap_formula": "7% + CPI, or 10%, whichever is lower",
    "attorney_review_required": True,
}


def _response(**overrides):
    base = {
        "loi_text": "x" * 520,
        "attorney_review_warning": "Buyer's attorney must review this LOI and the resulting purchase agreement "
                                    "before execution. This recommendation is unconditional.",
        "escrow_reference_present": True,
        "jurisdiction_flags": ["wa_rent_control_rcw59_18"],
    }
    base.update(overrides)
    return base


def test_run_a05_wa_acquisition_passes():
    fake = FakeModelClient(_response())
    result = run_a05(
        deal_type="acquisition", state_code="WA",
        selected_offer_strategy={"purchase_price": 4_900_000, "financing_structure": "75% LTV bank loan"},
        org_jurisdiction=WA_JURISDICTION, model_client=fake,
    )
    assert result.output.escrow_reference_present is True
    assert "wa_rent_control_rcw59_18" in result.output.jurisdiction_flags


def test_run_a05_rejects_missing_attorney_warning():
    fake = FakeModelClient(_response(attorney_review_warning="   "))
    with pytest.raises(A05ValidationError, match="attorney_review_warning"):
        run_a05(
            deal_type="acquisition", state_code="WA",
            selected_offer_strategy={"purchase_price": 4_900_000, "financing_structure": "x"},
            org_jurisdiction=WA_JURISDICTION, model_client=fake,
        )


def test_run_a05_rejects_escrow_reference_false():
    fake = FakeModelClient(_response(escrow_reference_present=False))
    with pytest.raises(A05ValidationError, match="escrow_reference_present"):
        run_a05(
            deal_type="acquisition", state_code="WA",
            selected_offer_strategy={"purchase_price": 4_900_000, "financing_structure": "x"},
            org_jurisdiction=WA_JURISDICTION, model_client=fake,
        )


def test_run_a05_rejects_missing_wa_rent_control_flag():
    fake = FakeModelClient(_response(jurisdiction_flags=[]))  # WA rent control active but flag omitted
    with pytest.raises(A05ValidationError, match="wa_rent_control_rcw59_18"):
        run_a05(
            deal_type="acquisition", state_code="WA",
            selected_offer_strategy={"purchase_price": 4_900_000, "financing_structure": "x"},
            org_jurisdiction=WA_JURISDICTION, model_client=fake,
        )


def test_run_a05_subject_to_requires_additional_flag():
    fake = FakeModelClient(_response(jurisdiction_flags=["wa_rent_control_rcw59_18"]))  # missing subject_to flag
    with pytest.raises(A05ValidationError, match="subject_to_review_required"):
        run_a05(
            deal_type="acquisition", state_code="WA",
            selected_offer_strategy={"purchase_price": 4_900_000, "financing_structure": "Subject-to existing financing"},
            org_jurisdiction=WA_JURISDICTION, non_standard_structure="subject_to", model_client=fake,
        )


def test_run_a05_subject_to_with_flag_passes():
    fake = FakeModelClient(_response(jurisdiction_flags=["wa_rent_control_rcw59_18", "subject_to_review_required"]))
    result = run_a05(
        deal_type="acquisition", state_code="WA",
        selected_offer_strategy={"purchase_price": 4_900_000, "financing_structure": "Subject-to existing financing"},
        org_jurisdiction=WA_JURISDICTION, non_standard_structure="subject_to", model_client=fake,
    )
    assert "subject_to_review_required" in result.output.jurisdiction_flags


def test_run_a05_non_wa_state_does_not_require_wa_flag():
    tx_jurisdiction = {"state_code": "TX", "rent_control_active": False, "attorney_review_required": True}
    fake = FakeModelClient(_response(jurisdiction_flags=[]))
    result = run_a05(
        deal_type="acquisition", state_code="TX",
        selected_offer_strategy={"purchase_price": 4_900_000, "financing_structure": "x"},
        org_jurisdiction=tx_jurisdiction, model_client=fake,
    )
    assert result.output.jurisdiction_flags == []


def test_run_a05_rejects_loi_text_too_short():
    fake = FakeModelClient(_response(loi_text="too short"))
    with pytest.raises(A05ValidationError, match="schema validation"):
        run_a05(
            deal_type="acquisition", state_code="WA",
            selected_offer_strategy={"purchase_price": 4_900_000, "financing_structure": "x"},
            org_jurisdiction=WA_JURISDICTION, model_client=fake,
        )
