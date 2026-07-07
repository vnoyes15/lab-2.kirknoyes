"""A-05 LOI Drafting Agent — Section 03, Section 18 (WA law), WA1/WA2.

Section 18/87 treat a handful of things as non-negotiable rather than merely
requested in the prompt: attorney_review_warning must be present, escrow_reference_present
must be true, and WA deals with active rent control must carry the
wa_rent_control_rcw59_18 flag. Those are re-checked here in Python after the model
responds — the prompt asks for them, but Section 10 EH3's "validation failure = always
unrecoverable" standard applies to legal-disclosure correctness exactly as much as it
does to underwriting math.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.schemas.a05_schema import A05Output

AGENT_ID = "a05"
MAX_TOKENS = 4096

NON_STANDARD_STRUCTURE_FLAGS = {
    "subject_to": "subject_to_review_required",
    "seller_financing": "seller_financing_review_required",
    "complex_jv": "complex_jv_review_required",
}


class A05ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A05Result:
    output: A05Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def run_a05(
    *,
    deal_type: str,
    state_code: str,
    selected_offer_strategy: dict,
    org_jurisdiction: dict,
    non_standard_structure: str | None = None,
    model_client: ModelClient | None = None,
) -> A05Result:
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    facts = {
        "deal_type": deal_type,
        "state_code": state_code,
        "selected_offer_strategy": selected_offer_strategy,
        "org_jurisdiction": org_jurisdiction,
        "non_standard_structure": non_standard_structure,
    }
    user_message = "Facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    try:
        output = A05Output.model_validate(response.parsed)
    except Exception as exc:
        raise A05ValidationError(f"A-05 output failed schema validation: {exc}", raw_output=response.parsed) from exc

    if not output.attorney_review_warning.strip():
        raise A05ValidationError(
            "attorney_review_warning must never be blank (Section 87, non-negotiable)",
            raw_output=response.parsed,
        )

    if output.escrow_reference_present is not True:
        raise A05ValidationError(
            "escrow_reference_present must be true (WA1/Section 87 — never held by either party directly)",
            raw_output=response.parsed,
        )

    if state_code == "WA" and org_jurisdiction.get("rent_control_active"):
        if "wa_rent_control_rcw59_18" not in output.jurisdiction_flags:
            raise A05ValidationError(
                "WA deals under active rent control must carry the wa_rent_control_rcw59_18 flag (Section 18 WA3-adjacent)",
                raw_output=response.parsed,
            )

    if non_standard_structure in NON_STANDARD_STRUCTURE_FLAGS:
        required_flag = NON_STANDARD_STRUCTURE_FLAGS[non_standard_structure]
        if required_flag not in output.jurisdiction_flags:
            raise A05ValidationError(
                f"{non_standard_structure} requires the additional attorney flag '{required_flag}' (WA2)",
                raw_output=response.parsed,
            )

    return A05Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
