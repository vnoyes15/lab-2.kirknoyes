"""A-03 Motivated Seller Profiler — Section 03.

DESIGN NOTE on access logging: Section 03/25 require every read of a seller profile
to write to seller_profile_access_log. This agent module stays a pure function (no DB
connection), consistent with every other agent — the API layer (arx/api/agents.py),
which already holds the request's DB connection and authenticated user_id, is where
that log entry actually gets written, right alongside the deal_snapshot write. Never
call run_a03 from anywhere that skips that logging step.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.schemas.a03_schema import A03Output

AGENT_ID = "a03"
MAX_TOKENS = 2048


class A03ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A03Result:
    output: A03Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def run_a03(
    *,
    deal_type: str,
    property_address: str,
    owner_name: str | None,
    ownership_duration_years: float | None,
    public_record_data: dict | None,
    prior_contact_history: dict | None = None,
    model_client: ModelClient | None = None,
) -> A03Result:
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    facts = {
        "deal_type": deal_type,
        "property_address": property_address,
        "owner_name": owner_name,
        "ownership_duration_years": ownership_duration_years,
        "public_record_data": public_record_data or "none available",
        "prior_contact_history": prior_contact_history or "no prior contact on record",
    }
    user_message = "Seller facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    try:
        output = A03Output.model_validate(response.parsed)
    except Exception as exc:  # pydantic.ValidationError
        raise A03ValidationError(f"A-03 output failed schema validation: {exc}", raw_output=response.parsed) from exc

    return A03Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
