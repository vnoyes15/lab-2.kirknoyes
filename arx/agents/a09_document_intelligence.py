"""A-09 Document Intelligence Agent — Section 03, Section 67.

Runs before every other agent when documents are present (R6, DI1). For rent rolls,
delegates the actual per-unit extraction to the deterministic
arx/agents/rent_roll_parser.py rather than asking the model to read spreadsheet cells
— the model is reserved for documents that are genuinely unstructured prose (OMs,
environmental reports, leases, appraisals, inspections, title commitments, loan term
sheets), where DI1/DI3's source-cited extraction actually requires judgment.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.agents.rent_roll_parser import RentRollSummary, parse_rent_roll
from arx.validation.schemas.a09_schema import A09Output

AGENT_ID = "a09"
MAX_TOKENS = 4096


class A09ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A09Result:
    output: A09Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def _rent_roll_to_a09_output(summary: RentRollSummary, filename: str) -> A09Output:
    """Wraps the deterministic rent roll parser's output in A-09's schema so
    downstream code (the API layer, orchestration) has one uniform A09Output shape
    regardless of whether extraction went through the model or the parser."""
    extracted_fields = {
        "gross_rent": {"value": summary.gross_rent, "source_page": None, "source_sheet": filename, "confidence": "high"},
        "vacancy_rate": {"value": summary.vacancy_rate, "source_page": None, "source_sheet": filename, "confidence": "high"},
        "average_rent": {"value": summary.average_rent, "source_page": None, "source_sheet": filename, "confidence": "high"},
        "unit_count": {"value": len(summary.units), "source_page": None, "source_sheet": filename, "confidence": "high"},
    }
    financials_mapping = [
        {"input_field": "gross_rent", "input_value": summary.gross_rent, "extraction_source": "rent_roll_parsed"},
        {"input_field": "vacancy_rate", "input_value": summary.vacancy_rate, "extraction_source": "rent_roll_parsed"},
    ]
    missing = []
    if summary.unparsed_line_count:
        missing.append(f"{summary.unparsed_line_count} rent roll line(s) could not be parsed")
    if summary.expiration_flag:
        extracted_fields["lease_expiration_concentration"] = {
            "value": summary.expiration_flag_detail, "source_page": None, "source_sheet": filename, "confidence": "high",
        }

    return A09Output(
        document_type_detected="rent_roll",
        extraction_completeness="complete" if not summary.unparsed_line_count else "partial",
        extracted_fields=extracted_fields,
        missing_required_fields=missing,
        conflicts_detected=[],
        appraisal_cross_reference=None,
        financials_db_mapping=financials_mapping,
    )


def run_a09(
    *,
    document_type: str,
    filename: str,
    file_bytes: bytes | None = None,
    document_text: str | None = None,
    existing_underwriting_snapshot: dict | None = None,
    model_client: ModelClient | None = None,
) -> A09Result:
    """document_type: caller's best guess, or "unknown". For document_type ==
    "rent_roll", file_bytes is parsed deterministically and the model is never
    called. For every other type, document_text (already extracted from the PDF/
    Word/Excel upstream — Section 05: PyMuPDF/python-docx/openpyxl) is sent to the
    model.
    """
    if document_type == "rent_roll":
        if file_bytes is None:
            raise ValueError("rent_roll documents require file_bytes, not document_text")
        summary = parse_rent_roll(file_bytes, filename)
        output = _rent_roll_to_a09_output(summary, filename)
        return A09Result(output=output, prompt_version="rent_roll_parser (no model)", input_tokens=0, output_tokens=0)

    if document_text is None:
        raise ValueError("Non-rent-roll documents require document_text")

    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    user_message_parts = [
        f"Declared document type: {document_type}",
        f"Filename: {filename}",
        "Document text:",
        document_text,
    ]
    if existing_underwriting_snapshot is not None:
        user_message_parts.append(f"Existing underwriting snapshot for cross-reference: {existing_underwriting_snapshot}")
    user_message = "\n\n".join(user_message_parts)

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    try:
        output = A09Output.model_validate(response.parsed)
    except Exception as exc:  # pydantic.ValidationError
        raise A09ValidationError(f"A-09 output failed schema validation: {exc}", raw_output=response.parsed) from exc

    return A09Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
