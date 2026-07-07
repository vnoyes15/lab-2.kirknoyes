"""A-01 Deal Screener — Section 03.

First filter for every deal. Unlike A-02/A-11, Section 15 does not define a math
validation suite for A-01 (there is no MV0) — it's intentionally a fast, incomplete-
data-tolerant screen, not a full underwriting. This agent relies on schema validation
only; a deal that clears A-01 still goes through A-02's full MV1-MV6 suite before any
number here is treated as reliable.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.schemas.a01_schema import A01Output

AGENT_ID = "a01"
MAX_TOKENS = 2048


class A01ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A01Result:
    output: A01Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def run_a01(
    *,
    deal_id: str,
    deal_type: str | None,
    property_address: str,
    asking_price: float | None,
    unit_count: int | None,
    land_area_sf: float | None,
    current_gross_rent: float | None,
    intended_use: str | None,
    target_cap_rate_range: tuple[float, float] | None,
    target_roc_range: tuple[float, float] | None,
    document_extraction_required: bool = False,
    model_client: ModelClient | None = None,
) -> A01Result:
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    facts = {
        "deal_id": deal_id,
        "deal_type": deal_type or "unknown — infer from the facts below",
        "property_address": property_address,
        "asking_price": asking_price,
        "unit_count": unit_count,
        "land_area_sf": land_area_sf,
        "current_gross_rent": current_gross_rent,
        "intended_use": intended_use,
        "org_target_cap_rate_range": target_cap_rate_range,
        "org_target_roc_range": target_roc_range,
        "document_extraction_required": document_extraction_required,
    }
    user_message = "Deal facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    try:
        output = A01Output.model_validate(response.parsed)
    except Exception as exc:  # pydantic.ValidationError
        raise A01ValidationError(f"A-01 output failed schema validation: {exc}", raw_output=response.parsed) from exc

    return A01Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
