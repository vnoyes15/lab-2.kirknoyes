"""A-02 Underwriting Agent — Section 03, Section 15.

Full acquisition financial model. The model produces the judgment-heavy fields
(NOI construction from rent/vacancy/opex, cap rate, DSCR, cash-on-cash, sensitivity,
load-bearing assumptions); Python computes annual_debt_service deterministically from
loan terms (Section 87 is explicit this one field is "Not model-estimated") and derives
dscr_hard_fail/dscr_warning from whatever DSCR the model reports. The full MV1-MV6
suite (arx/validation/acquisition_validation.py) then re-checks every number for
internal consistency before anything is treated as usable — a validation failure here
is unrecoverable (Section 10 EH3): it is never silently patched by recomputing over
the model's output, it is reported so the run can be retried or escalated.

NOT YET IMPLEMENTED in this Phase 2 version (both are later-phase features per Section
07): portfolio impact context (Section 69, Phase 5) and lender matching (Section 43,
Phase 3). Neither is silently faked — they're simply absent from the output rather
than stubbed with placeholder data.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.loan_math import compute_annual_debt_service
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.acquisition_validation import validate_acquisition_output
from arx.validation.results import ValidationSuiteResult
from arx.validation.schemas.a02_schema import A02Output

AGENT_ID = "a02"
MAX_TOKENS = 4096
DSCR_WARNING_THRESHOLD = 1.25
DSCR_HARD_FAIL_THRESHOLD = 1.00

SENSITIVITY_SCENARIO_ORDER = ["rent_-10pct", "rent_-5pct", "base", "rent_+5pct", "rent_+10pct"]


class A02ValidationError(AgentValidationError):
    """Raised when either schema or math validation fails (Section 10 EH3:
    "Validation failure = always unrecoverable"). Carries enough detail for the
    caller to write a complete error_log record (EH4)."""


@dataclass(frozen=True)
class A02Result:
    output: A02Output
    prompt_version: str
    input_tokens: int
    output_tokens: int
    validation: ValidationSuiteResult


def run_a02(
    *,
    gross_rent_hint: float | None,
    purchase_price: float,
    asset_type: str,
    submarket: str,
    uw_defaults: dict,
    loan_amount: float,
    ltv: float,
    interest_rate: float,
    amortization_years: int,
    comps: list[dict] | None = None,
    model_client: ModelClient | None = None,
) -> A02Result:
    """uw_defaults: the org's active acquisition-track uw_config (vacancy,
    property_management, maintenance, capex_reserves, insurance_pct_of_price) —
    Section 32/Section 04 ZONIQ DEFAULTS. Raises A02ValidationError if the model's
    output fails schema or math validation.
    """
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    annual_debt_service = compute_annual_debt_service(loan_amount, interest_rate, amortization_years)

    facts = {
        "gross_rent_hint": gross_rent_hint,
        "purchase_price": purchase_price,
        "asset_type": asset_type,
        "submarket": submarket,
        "org_underwriting_defaults": uw_defaults,
        "loan_amount": loan_amount,
        "ltv": ltv,
        "interest_rate": interest_rate,
        "amortization_years": amortization_years,
        "annual_debt_service_given": annual_debt_service,
        "comps": comps if comps else "none available",
    }
    user_message = "Deal facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    raw = dict(response.parsed)

    # Python-authoritative fields (Section 87) — never taken from the model.
    raw["purchase_price"] = purchase_price
    raw["loan_amount"] = loan_amount
    raw["ltv"] = ltv
    raw["interest_rate"] = interest_rate
    raw["amortization_years"] = amortization_years
    raw["annual_debt_service"] = annual_debt_service
    raw["debt_service"] = annual_debt_service  # alias expected by the MV3 check's parameter name
    dscr = raw.get("dscr")
    raw["dscr_hard_fail"] = (dscr is not None) and dscr < DSCR_HARD_FAIL_THRESHOLD
    raw["dscr_warning"] = (dscr is not None) and dscr < DSCR_WARNING_THRESHOLD

    try:
        output = A02Output.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError
        raise A02ValidationError(f"A-02 output failed schema validation: {exc}", raw_output=raw) from exc

    validation_input = dict(raw)
    validation_input["operating_expenses"] = raw["operating_expenses"]
    if "sensitivity_table" in raw:
        validation_input["sensitivity_scenario_order"] = SENSITIVITY_SCENARIO_ORDER
    validation = validate_acquisition_output(validation_input)

    if not validation.passed:
        raise A02ValidationError(
            "A-02 output failed math validation (MV1-MV6)",
            raw_output=raw, failed_checks=validation.to_dict(),
        )

    return A02Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        validation=validation,
    )
