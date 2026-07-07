"""A-10 Land Acquisition Agent — Section 03, Section 66.

Like A-01, Section 15 defines no dedicated math validation suite for A-10 — it's a
preliminary screen, not a full pro forma (that's A-11's job, with the real DV1-DV5
suite). Schema validation is the enforcement boundary here.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.schemas.a10_schema import A10Output

AGENT_ID = "a10"
MAX_TOKENS = 2048


class A10ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A10Result:
    output: A10Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def run_a10(
    *,
    property_address: str,
    land_area_sf: float | None,
    asking_price: float | None,
    intended_use: str | None,
    zoning_info: dict | None,
    site_info: dict | None,
    owner_name: str | None,
    ownership_duration_years: float | None,
    entity_type: str | None,
    org_land_cost_per_unit_benchmark: float | None = None,
    model_client: ModelClient | None = None,
) -> A10Result:
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    facts = {
        "property_address": property_address,
        "land_area_sf": land_area_sf,
        "asking_price": asking_price,
        "intended_use": intended_use,
        "zoning_info": zoning_info or "not available",
        "site_info": site_info or "not available",
        "owner_name": owner_name,
        "ownership_duration_years": ownership_duration_years,
        "entity_type": entity_type,
        "org_land_cost_per_unit_benchmark": org_land_cost_per_unit_benchmark,
    }
    user_message = "Land deal facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    try:
        output = A10Output.model_validate(response.parsed)
    except Exception as exc:
        raise A10ValidationError(f"A-10 output failed schema validation: {exc}", raw_output=response.parsed) from exc

    return A10Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
