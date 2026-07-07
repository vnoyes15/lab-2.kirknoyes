"""A-13 Capital Raise Intelligence Agent — Section 03, Section 64.

Section 87: "no_track_record_disclosure !R — Required when deals_closed = 0. Explicit
statement... Never omit when applicable." Checked here in Python rather than trusted
to the model, same pattern as A-07's confidence_disclosure requirement.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.schemas.a13_schema import A13Output

AGENT_ID = "a13"
MAX_TOKENS = 4096


class A13ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A13Result:
    output: A13Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def run_a13(
    *,
    deal_context: dict,
    lp_profiles: list[dict],
    org_deal_history: dict,
    model_client: ModelClient | None = None,
) -> A13Result:
    """org_deal_history: {"deals_closed": int, "total_equity_deployed": float,
    "avg_return_vs_projection": float | None, "strongest_precedent": str | None}."""
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    facts = {
        "deal_context": deal_context,
        "lp_profiles": lp_profiles if lp_profiles else "no LPs on file",
        "org_deal_history": org_deal_history,
    }
    user_message = "Facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    try:
        output = A13Output.model_validate(response.parsed)
    except Exception as exc:
        raise A13ValidationError(f"A-13 output failed schema validation: {exc}", raw_output=response.parsed) from exc

    if output.track_record_summary.deals_closed == 0 and not output.no_track_record_disclosure:
        raise A13ValidationError(
            "no_track_record_disclosure is required when deals_closed = 0 (Section 87 — never omit)",
            raw_output=response.parsed,
        )

    return A13Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
