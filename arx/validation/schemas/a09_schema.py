"""A-09 Document Intelligence Agent output schema — Section 87."""
from typing import Any, Literal

from pydantic import BaseModel


class ExtractedField(BaseModel):
    value: Any
    source_page: int | None = None
    source_sheet: str | None = None
    confidence: Literal["high", "medium", "low"]


class ExtractionConflict(BaseModel):
    field: str
    value_a: Any
    source_a: str
    value_b: Any
    source_b: str


class AppraisalCrossReference(BaseModel):
    discrepancy_found: bool
    notes: str


class FinancialsMapping(BaseModel):
    input_field: str
    input_value: Any
    # Section 87 pins this to the single literal "a09_extracted", written for the case
    # where A-09's own model reasoning produced the value. But Section 16/06 are
    # explicit that a value obtained via the dedicated rent roll parser (deterministic,
    # no model involved — arx/agents/rent_roll_parser.py) must be tagged
    # "rent_roll_parsed" instead, specifically so A-02 can prefer it over anything
    # else ("A-02 always prefers parsed rent roll over manually entered gross rent").
    # Both are legitimate values of financials.extraction_source (Section 06); A-09's
    # output schema needs to be able to express either, not just the one Section 87
    # happened to spell out.
    extraction_source: Literal["a09_extracted", "rent_roll_parsed"] = "a09_extracted"


class A09Output(BaseModel):
    document_type_detected: Literal[
        "om", "rent_roll", "lease", "title_commitment", "environmental",
        "appraisal", "inspection", "loan_term_sheet",
    ]
    extraction_completeness: Literal["complete", "partial", "failed"]
    extracted_fields: dict[str, ExtractedField]
    missing_required_fields: list[str]
    conflicts_detected: list[ExtractionConflict]
    appraisal_cross_reference: AppraisalCrossReference | None = None
    financials_db_mapping: list[FinancialsMapping]
