"""A-04 Offer Strategy Agent — Section 03.

Unlike A-02/A-11, Section 15 defines no math validation suite for A-04's per-strategy
return figures — there's no MV/DV-numbered cross-check for them. Schema validation
(exactly 3 strategies, minimum 2 risks each, minimum rationale length) is the
enforcement boundary here; the prompt itself carries the "recompute from this
strategy's own price" instruction since there's nothing downstream re-deriving it
deterministically the way A-02's DSCR gets checked against Python-computed debt service.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.schemas.a04_schema import A04Output

AGENT_ID = "a04"
MAX_TOKENS = 4096


class A04ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A04Result:
    output: A04Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def run_a04(
    *,
    deal_type: str,
    underwriting_snapshot: dict,
    seller_profile: dict,
    comps: list[dict] | None = None,
    feasibility_contingency_days_default: int | None = None,
    model_client: ModelClient | None = None,
) -> A04Result:
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    facts = {
        "deal_type": deal_type,
        "underwriting_snapshot": underwriting_snapshot,
        "seller_profile": seller_profile,
        "comps": comps if comps else "none available",
        "org_feasibility_contingency_days_default": feasibility_contingency_days_default,
    }
    user_message = "Facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    try:
        output = A04Output.model_validate(response.parsed)
    except Exception as exc:
        raise A04ValidationError(f"A-04 output failed schema validation: {exc}", raw_output=response.parsed) from exc

    if deal_type in ("land", "development") and output.feasibility_contingency_days is None:
        raise A04ValidationError(
            "feasibility_contingency_days is required for land/development deals (Section 87)",
            raw_output=response.parsed,
        )

    return A04Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
