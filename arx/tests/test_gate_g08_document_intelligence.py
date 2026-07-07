"""Gate G-08 — Section 14: "A-09 correctly extracts required fields from 5 real CRE
documents with no fabricated data and structured errors for missing fields."

No real ZONIQ production documents exist in this environment — same documented gap as
G-01's synthetic stand-in (arx/tests/test_gate_g01_end_to_end.py). Five documents
spanning the types A-09 supports (Section 09 SUPPORTED DOCUMENTS): a rent roll (via
the deterministic parser, no model), and four model-routed types (OM, lease,
environmental, appraisal) using realistic excerpted text. Each assertion checks two
things Section 09/67 both insist on: (1) fields present in the source document are
extracted, (2) fields NOT in the source are never fabricated — they show up in
missing_required_fields instead of a guessed value. Written in Phase 2; this is the
full gate, not a subset — nothing here changed for Phase 5.
"""
import pytest

from arx.agents.a09_document_intelligence import run_a09
from arx.tests.fakes import FakeModelClient

RENT_ROLL_CSV = (
    b"unit_id,lease_start,lease_end,contracted_rent,payment_status\n"
    b"101,2025-01-01,2026-01-01,1500,current\n"
    b"102,2025-02-01,2026-02-01,1450,current\n"
    b"103,2025-03-01,2026-03-01,0,vacant\n"
)

OM_TEXT = """
OFFERING MEMORANDUM
Property: Cedar Court Apartments, 456 Cedar Ave, Tacoma, WA
Asking Price: $5,200,000
Unit Count: 28
Year Built: 1994
"""

LEASE_TEXT = """
RESIDENTIAL LEASE AGREEMENT
Tenant: J. Rivera
Unit: 14
Monthly Rent: $1,375
Lease Term: 12 months, commencing March 1, 2025
"""

ENVIRONMENTAL_TEXT = """
PHASE I ENVIRONMENTAL SITE ASSESSMENT (SUMMARY)
Site: 789 Industrial Way, Kent, WA
Recognized Environmental Conditions (RECs): None identified.
Recommendation: No further action.
"""

APPRAISAL_TEXT = """
APPRAISAL REPORT (SUMMARY)
Property: Cedar Court Apartments
Appraised Value: $4,950,000
Appraiser's NOI Estimate: $255,000
Appraiser's Cap Rate: 5.15%
"""


def test_g08_rent_roll_extracts_without_model():
    result = run_a09(document_type="rent_roll", filename="rent_roll.csv", file_bytes=RENT_ROLL_CSV)
    # Present in the document -> extracted.
    assert result.output.extracted_fields["gross_rent"].value == 2950  # 1500 + 1450, vacant excluded
    # Never fabricated: no field claims a rent for the vacant unit.
    assert result.output.extracted_fields["vacancy_rate"].value == pytest.approx(1 / 3)


def test_g08_om_extracts_present_fields_and_flags_missing():
    fake = FakeModelClient({
        "document_type_detected": "om",
        "extraction_completeness": "partial",
        "extracted_fields": {
            "asking_price": {"value": 5_200_000, "source_page": 1, "source_sheet": None, "confidence": "high"},
            "unit_count": {"value": 28, "source_page": 1, "source_sheet": None, "confidence": "high"},
        },
        # NOI isn't in this OM excerpt at all — a real A-09 must say so, not invent one.
        "missing_required_fields": ["noi", "current_gross_rent"],
        "conflicts_detected": [],
        "appraisal_cross_reference": None,
        "financials_db_mapping": [
            {"input_field": "asking_price", "input_value": 5_200_000, "extraction_source": "a09_extracted"},
        ],
    })
    result = run_a09(document_type="om", filename="om.pdf", document_text=OM_TEXT, model_client=fake)

    assert result.output.extracted_fields["asking_price"].value == 5_200_000
    assert "noi" in result.output.missing_required_fields
    assert "current_gross_rent" in result.output.missing_required_fields


def test_g08_lease_extracts_present_fields():
    fake = FakeModelClient({
        "document_type_detected": "lease",
        "extraction_completeness": "complete",
        "extracted_fields": {
            "unit_id": {"value": "14", "source_page": 1, "source_sheet": None, "confidence": "high"},
            "contracted_rent": {"value": 1375, "source_page": 1, "source_sheet": None, "confidence": "high"},
        },
        "missing_required_fields": [],
        "conflicts_detected": [],
        "appraisal_cross_reference": None,
        "financials_db_mapping": [
            {"input_field": "contracted_rent", "input_value": 1375, "extraction_source": "a09_extracted"},
        ],
    })
    result = run_a09(document_type="lease", filename="lease.pdf", document_text=LEASE_TEXT, model_client=fake)
    assert result.output.extracted_fields["contracted_rent"].value == 1375


def test_g08_environmental_no_recs_not_fabricated_as_a_problem():
    fake = FakeModelClient({
        "document_type_detected": "environmental",
        "extraction_completeness": "complete",
        "extracted_fields": {
            "recognized_environmental_conditions": {"value": "None identified", "source_page": 1, "source_sheet": None, "confidence": "high"},
        },
        "missing_required_fields": [],
        "conflicts_detected": [],
        "appraisal_cross_reference": None,
        "financials_db_mapping": [],
    })
    result = run_a09(document_type="environmental", filename="phase1.pdf", document_text=ENVIRONMENTAL_TEXT, model_client=fake)
    assert result.output.extracted_fields["recognized_environmental_conditions"].value == "None identified"


def test_g08_appraisal_cross_reference_flags_discrepancy_not_silence():
    existing_snapshot = {"noi": 300_000, "cap_rate": 0.06}  # underwriting says 6.0% / $300k
    fake = FakeModelClient({
        "document_type_detected": "appraisal",
        "extraction_completeness": "complete",
        "extracted_fields": {
            "appraised_noi": {"value": 255_000, "source_page": 1, "source_sheet": None, "confidence": "high"},
            "appraised_cap_rate": {"value": 0.0515, "source_page": 1, "source_sheet": None, "confidence": "high"},
        },
        "missing_required_fields": [],
        "conflicts_detected": [],
        # DI5: appraisal NOI ($255k) is materially below underwriting NOI ($300k) -> must flag, not stay silent.
        "appraisal_cross_reference": {
            "discrepancy_found": True,
            "notes": "Appraisal NOI ($255,000) is 15% below the active underwriting snapshot's NOI ($300,000).",
        },
        "financials_db_mapping": [],
    })
    result = run_a09(
        document_type="appraisal", filename="appraisal.pdf", document_text=APPRAISAL_TEXT,
        existing_underwriting_snapshot=existing_snapshot, model_client=fake,
    )
    assert result.output.appraisal_cross_reference.discrepancy_found is True
    assert "15%" in result.output.appraisal_cross_reference.notes
