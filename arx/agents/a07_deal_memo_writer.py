"""A-07 Deal Memo Writer — Section 03, Section 87.

Section 87: "financial_summary_metrics R — Must match active A-02 or A-11 snapshot.
Discrepancies = unrecoverable error." This agent mechanically diffs the model's
financial_summary_metrics against the underwriting snapshot it was given — any metric
the model echoes that doesn't match the snapshot's own value (within the same relative
tolerance as the math validation suites) fails the run rather than being silently
trusted (Section 10 EH3).
"""
from dataclasses import dataclass

from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, ModelResponse, get_default_model_client
from arx.agents.prompt_loader import load_active_prompt
from arx.validation.schemas.a07_schema import A07Output
from arx.validation.tolerance import approx_equal

AGENT_ID = "a07"
MAX_TOKENS = 4096
METRIC_TOLERANCE = 0.001


class A07ValidationError(AgentValidationError):
    pass


@dataclass(frozen=True)
class A07Result:
    output: A07Output
    prompt_version: str
    input_tokens: int
    output_tokens: int


def _check_metrics_match_snapshot(metrics: dict[str, float], snapshot_output: dict) -> list[dict]:
    """Returns a list of mismatch records (empty if everything matches). Only checks
    metrics that are both in the memo's financial_summary_metrics AND present on the
    snapshot — a metric the snapshot simply doesn't have isn't a discrepancy to check
    against (e.g. an acquisition snapshot has no irr to compare)."""
    mismatches = []
    for metric_name, memo_value in metrics.items():
        if metric_name not in snapshot_output:
            continue
        snapshot_value = snapshot_output[metric_name]
        if not approx_equal(snapshot_value, memo_value, METRIC_TOLERANCE):
            mismatches.append({"metric": metric_name, "memo_value": memo_value, "snapshot_value": snapshot_value})
    return mismatches


def run_a07(
    *,
    memo_track: str,
    underwriting_snapshot: dict,
    confidence_score: str,
    property_context: dict,
    audience_version: str,
    model_client: ModelClient | None = None,
) -> A07Result:
    prompt = load_active_prompt(AGENT_ID)
    client = model_client or get_default_model_client()

    facts = {
        "memo_track": memo_track,
        "underwriting_snapshot": underwriting_snapshot,
        "confidence_score": confidence_score,
        "property_context": property_context,
        "audience_version": audience_version,
    }
    user_message = "Facts:\n" + "\n".join(f"  {k}: {v}" for k, v in facts.items())

    response: ModelResponse = client.generate_json(prompt.prompt_text, user_message, MAX_TOKENS)
    raw = dict(response.parsed)

    try:
        output = A07Output.model_validate(raw)
    except Exception as exc:
        raise A07ValidationError(f"A-07 output failed schema validation: {exc}", raw_output=raw) from exc

    mismatches = _check_metrics_match_snapshot(output.financial_summary_metrics, underwriting_snapshot)
    if mismatches:
        raise A07ValidationError(
            "A-07 financial_summary_metrics do not match the active underwriting snapshot",
            raw_output=raw, failed_checks={"mismatches": mismatches},
        )

    if confidence_score == "low" and not output.confidence_disclosure:
        raise A07ValidationError(
            "Low-confidence snapshot but memo has no confidence_disclosure (Arx never hides low confidence)",
            raw_output=raw,
        )

    return A07Result(
        output=output,
        prompt_version=prompt.version,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
