import pytest

from arx.agents.a09_document_intelligence import run_a09
from arx.tests.fakes import FakeModelClient

CSV_SAMPLE = (
    "unit_id,lease_start,lease_end,contracted_rent,payment_status\n"
    "101,2025-01-01,2026-01-01,1500,current\n"
    "102,2025-02-01,2026-02-01,0,vacant\n"
).encode("utf-8")


def test_rent_roll_path_uses_parser_not_model():
    result = run_a09(document_type="rent_roll", filename="rr.csv", file_bytes=CSV_SAMPLE)
    assert result.output.document_type_detected == "rent_roll"
    assert result.output.extracted_fields["gross_rent"].value == 1500
    assert result.output.extracted_fields["vacancy_rate"].value == 0.5
    assert result.input_tokens == 0 and result.output_tokens == 0


def test_rent_roll_path_requires_file_bytes():
    with pytest.raises(ValueError, match="file_bytes"):
        run_a09(document_type="rent_roll", filename="rr.csv", document_text="not bytes")


def test_om_document_uses_model():
    fake_response = {
        "document_type_detected": "om",
        "extraction_completeness": "complete",
        "extracted_fields": {
            "asking_price": {"value": 5_000_000, "source_page": 3, "source_sheet": None, "confidence": "high"},
        },
        "missing_required_fields": [],
        "conflicts_detected": [],
        "appraisal_cross_reference": None,
        "financials_db_mapping": [
            {"input_field": "asking_price", "input_value": 5_000_000, "extraction_source": "a09_extracted"},
        ],
    }
    fake_client = FakeModelClient(fake_response, input_tokens=500, output_tokens=300)

    result = run_a09(
        document_type="om", filename="offering_memo.pdf", document_text="Offering Memorandum text...",
        model_client=fake_client,
    )

    assert result.output.document_type_detected == "om"
    assert result.output.extracted_fields["asking_price"].value == 5_000_000
    assert result.prompt_version == "1.0.0"
    assert result.input_tokens == 500 and result.output_tokens == 300
    assert len(fake_client.calls) == 1


def test_non_rent_roll_requires_document_text():
    with pytest.raises(ValueError, match="document_text"):
        run_a09(document_type="om", filename="om.pdf")


def test_appraisal_cross_reference_passed_through():
    fake_response = {
        "document_type_detected": "appraisal",
        "extraction_completeness": "complete",
        "extracted_fields": {},
        "missing_required_fields": [],
        "conflicts_detected": [],
        "appraisal_cross_reference": {"discrepancy_found": True, "notes": "Appraisal NOI is 15% below underwriting."},
        "financials_db_mapping": [],
    }
    fake_client = FakeModelClient(fake_response)

    result = run_a09(
        document_type="appraisal", filename="appraisal.pdf", document_text="Appraisal text...",
        existing_underwriting_snapshot={"noi": 300_000, "cap_rate": 0.06},
        model_client=fake_client,
    )

    assert result.output.appraisal_cross_reference.discrepancy_found is True
    # The existing snapshot must actually have been sent to the model for cross-reference.
    assert "existing underwriting snapshot" in fake_client.calls[0]["user_message"].lower()
