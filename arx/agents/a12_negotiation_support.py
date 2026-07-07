"""A-12 Negotiation Support Agent — Section 03, Section 42.

The "exactly one recommended=true" and "exactly 3 response options" rules are enforced
at the schema level (arx/validation/schemas/a12_schema.py) since they're structural,
not arithmetic — there's no MV/DV-numbered cross-check for deal_impact the way A-02's
DSCR gets checked against Python-computed debt service, so schema validation is the
enforcement boundary here (same as A-04).
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.schemas.a12_schema import A12Output

AGENT_ID = "a12"
MAX_TOKENS = 4096


class A12ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A12Result:
    output: A12Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def run_a12(
    *,
    original_offer_strategy: dict,
    seller_counter_terms: dict,
    underwriting_snapshot: dict,
    seller_profile: dict | None = None,
    comparable_precedents: list[dict] | None = None,
    org_return_thresholds: dict | None = None,
    model_client: ModelClient | None = None,
) -> A12Result:
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    facts = {
        "original_offer_strategy": original_offer_strategy,
        "seller_counter_terms": seller_counter_terms,
        "underwriting_snapshot": underwriting_snapshot,
        "seller_profile": seller_profile or "not available",
        "comparable_precedents": comparable_precedents if comparable_precedents else "none available",
        "org_return_thresholds": org_return_thresholds or "not configured",
    }
    user_message = "Facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    try:
        output = A12Output.model_validate(response.parsed)
    except Exception as exc:
        raise A12ValidationError(f"A-12 output failed schema validation: {exc}", raw_output=response.parsed) from exc

    return A12Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
