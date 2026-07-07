"""A-08 Outreach Agent — Section 03, Section 22.

Suppression and daily-limit checks happen in Python BEFORE the model is ever called —
if a contact is suppressed or the org is over its daily send limit, this raises
immediately and no message is drafted at all. suppression_checked/daily_limit_checked
in the output are then just a record that these Python checks ran and passed, never
values the model reports or that get trusted from it.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.schemas.a08_schema import A08Output

AGENT_ID = "a08"
MAX_TOKENS = 2048
DEFAULT_DAILY_SEND_LIMIT = 50


class A08ValidationError(AgentValidationError):
    pass


class A08SuppressedError(A08ValidationError):
    """Raised before any model call — drafting outreach to a suppressed contact is
    never attempted, not even to produce a draft for review."""


class A08DailyLimitError(A08ValidationError):
    """Raised before any model call — Section 22's daily send limit is enforced
    pre-emptively, not discovered after drafting."""


@dataclass(frozen=True)
class A08Result:
    output: A08Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def run_a08(
    *,
    recipient_type: str,
    recipient_context: dict,
    channel: str,
    deal_context: dict | None,
    is_suppressed: bool,
    daily_send_count_so_far: int,
    daily_send_limit: int = DEFAULT_DAILY_SEND_LIMIT,
    model_client: ModelClient | None = None,
) -> A08Result:
    if is_suppressed:
        raise A08SuppressedError(
            "Recipient is on the suppression list — outreach was not drafted (Section 22)",
            raw_output={"recipient_type": recipient_type, "channel": channel},
        )
    if daily_send_count_so_far >= daily_send_limit:
        raise A08DailyLimitError(
            f"Daily send limit reached ({daily_send_count_so_far}/{daily_send_limit}) — "
            f"outreach was not drafted (Section 22)",
            raw_output={"recipient_type": recipient_type, "channel": channel},
        )

    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    facts = {
        "recipient_type": recipient_type,
        "recipient_context": recipient_context,
        "channel": channel,
        "deal_context": deal_context or "not deal-specific",
    }
    user_message = "Outreach facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    raw = dict(response.parsed)
    # Verified above, before the model was ever called — never asked of the model.
    raw["suppression_checked"] = True
    raw["daily_limit_checked"] = True

    try:
        output = A08Output.model_validate(raw)
    except Exception as exc:
        raise A08ValidationError(f"A-08 output failed schema validation: {exc}", raw_output=raw) from exc

    return A08Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
