"""A-11 Development Pro Forma Agent — Section 03, Section 15.

Wires the Phase 1 development validation suite (DV1-DV5,
arx/validation/development_validation.py) the same way A-02 wires the acquisition
suite: the model reports the full set of numbers, Python validates every one of them
for internal consistency before anything is treated as usable, and any inconsistency
is unrecoverable (Section 10 EH3) rather than silently patched.

DV5 covers two independent sensitivity axes here (cost overrun and absorption delay —
see the schema module's docstring for why they're two separate dicts, not one table).
validate_development_output() only runs the directional check for one axis
(cost_overrun_sensitivity, passed in as its generic "sensitivity_table" parameter);
the second axis (absorption_delay_sensitivity) is checked with a second, explicit call
to the same underlying primitive and merged into one combined result below.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.acquisition_validation import check_sensitivity_directional
from arx.validation.development_validation import validate_development_output
from arx.validation.results import ValidationSuiteResult
from arx.validation.schemas.a11_schema import A11Output

AGENT_ID = "a11"
MAX_TOKENS = 4096

COST_OVERRUN_ORDER = ["cost_overrun_15pct", "cost_overrun_10pct", "cost_overrun_5pct", "base"]
ABSORPTION_DELAY_ORDER = ["absorption_delay_6mo", "absorption_delay_3mo", "base"]


class A11ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A11Result:
    output: A11Output
    prompt_version: str
    input_tokens: int
    output_tokens: int
    validation: ValidationSuiteResult


def run_a11(
    *,
    land_cost: float,
    unit_count: int | None,
    asset_type: str,
    dev_defaults: dict,
    exit_cap_rate: float,
    entitlement_context: dict | None = None,
    rent_comps: list[dict] | None = None,
    model_client: ModelClient | None = None,
) -> A11Result:
    """dev_defaults: the org's active development-track uw_config (soft_costs_pct_of_hard_min/max,
    construction_contingency_pct_min/max, construction_loan_ltc, stabilized_occupancy)."""
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    facts = {
        "land_cost": land_cost,
        "unit_count": unit_count,
        "asset_type": asset_type,
        "org_development_defaults": dev_defaults,
        "exit_cap_rate": exit_cap_rate,
        "entitlement_context": entitlement_context or "not available",
        "rent_comps": rent_comps if rent_comps else "none available",
    }
    user_message = "Development deal facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    raw = dict(response.parsed)

    try:
        output = A11Output.model_validate(raw)
    except Exception as exc:
        raise A11ValidationError(f"A-11 output failed schema validation: {exc}", raw_output=raw) from exc

    validation_input = dict(raw)
    validation_input["sensitivity_table"] = raw["cost_overrun_sensitivity"]
    validation_input["sensitivity_scenario_order"] = COST_OVERRUN_ORDER
    suite = validate_development_output(validation_input)

    absorption_check = check_sensitivity_directional(
        raw["absorption_delay_sensitivity"], "return_on_cost", ABSORPTION_DELAY_ORDER,
    )
    combined = ValidationSuiteResult(suite.results + [absorption_check])

    if not combined.passed:
        raise A11ValidationError(
            "A-11 output failed math validation (DV1-DV5)",
            raw_output=raw, failed_checks=combined.to_dict(),
        )

    return A11Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        validation=combined,
    )
