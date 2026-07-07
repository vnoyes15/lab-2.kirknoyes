"""A-06 Due Diligence Coordinator — Section 03, Section 18 WA3.

The checklist category lists are Python constants, not model-generated — Section 03's
ACQUISITION TRACK / LAND-DEVELOPMENT TRACK lists are a fixed contract with the
operator ("this deal has exactly these DD categories"), so completeness can't depend
on whether the model happened to remember all of them. deal_advancement_blocked is
likewise Python-computed from the validated checklist, never trusted from the model.
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.schemas.a06_schema import A06Output

AGENT_ID = "a06"
MAX_TOKENS = 4096

# Section 03 A-06 ACQUISITION TRACK.
ACQUISITION_CATEGORIES = [
    "physical_inspection", "financial_document_verification", "legal_and_title_review",
    "lease_audit", "loan_requirements",
]
# Section 03 A-06 LAND/DEVELOPMENT TRACK.
LAND_DEVELOPMENT_CATEGORIES = [
    "title_and_survey", "zoning_and_entitlement_review", "environmental_assessment",
    "geotechnical_report", "utility_confirmation", "construction_cost_validation",
    "entitlement_timeline_assessment",
]

BLOCKING_STATUSES = ("flagged", "not_started")


class A06ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A06Result:
    output: A06Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def categories_for_track(dd_track: str) -> list[str]:
    if dd_track == "acquisition":
        return ACQUISITION_CATEGORIES
    if dd_track == "land_development":
        return LAND_DEVELOPMENT_CATEGORIES
    raise ValueError(f"Unknown dd_track: {dd_track!r}")


def run_a06(
    *,
    dd_track: str,
    deal_facts: dict,
    is_wa_multifamily: bool = False,
    model_client: ModelClient | None = None,
) -> A06Result:
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()
    required_categories = categories_for_track(dd_track)

    facts = {
        "dd_track": dd_track,
        "required_categories": required_categories,
        "deal_facts": deal_facts,
        "is_wa_multifamily": is_wa_multifamily,
    }
    user_message = "DD facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    raw = dict(response.parsed)
    # deal_advancement_blocked is never asked of the model (see module docstring) —
    # seed a placeholder so schema validation doesn't reject a required field the
    # model was never told to produce; the real value is computed and substituted in below.
    raw.setdefault("deal_advancement_blocked", False)

    try:
        output = A06Output.model_validate(raw)
    except Exception as exc:
        raise A06ValidationError(f"A-06 output failed schema validation: {exc}", raw_output=raw) from exc

    # Completeness: exactly the required categories, no more, no less (N7 — a DD
    # checklist missing a required category isn't a minor gap, it's the whole point
    # of this agent failing silently).
    returned_categories = {item.category for item in output.checklist_items}
    missing = set(required_categories) - returned_categories
    extra = returned_categories - set(required_categories)
    if missing or extra:
        raise A06ValidationError(
            f"Checklist categories don't match the required set for track '{dd_track}': "
            f"missing={sorted(missing)}, unexpected={sorted(extra)}",
            raw_output=raw,
        )

    # WA3: required and non-optional for all WA multifamily deals.
    if is_wa_multifamily and output.wa_rent_compliance_item is None:
        raise A06ValidationError(
            "wa_rent_compliance_item is required and non-optional for WA multifamily deals (Section 18 WA3)",
            raw_output=raw,
        )

    all_items = list(output.checklist_items) + ([output.wa_rent_compliance_item] if output.wa_rent_compliance_item else [])
    deal_advancement_blocked = any(item.status in BLOCKING_STATUSES for item in all_items)
    output = output.model_copy(update={"deal_advancement_blocked": deal_advancement_blocked})

    return A06Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
