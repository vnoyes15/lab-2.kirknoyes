"""Real agent nodes for the four Phase 2 agents (A-01, A-02, A-07, A-09).

SCOPE BOUNDARY — read this before wiring more into the graph. Section 07 Phase 2 asks
for A-09 -> A-01 -> A-02 -> A-07 to exist and be callable; the orchestration layer's
"Full state management, handoffs" is explicitly Phase 5 work (Section 07). Persisting
snapshots, activating them, and enforcing R5 ("downstream agents pull user-designated
active snapshot — never the most recent automatically") all require a human checkpoint
between steps (Section 13: "New snapshot never auto-activates — user designates
explicitly") — modeling that properly in LangGraph means using its interrupt/resume
support, which is Phase 5 orchestration-polish scope, not Phase 2.

So: these nodes are real (they call the actual agents, not placeholders), and they're
useful today for testing that the graph topology drives real agent logic correctly
end-to-end in memory. But arx/api/agents.py — one API call per agent, with an explicit
/activate step in between — remains the actual Phase 2 production invocation path.
Nothing here writes to the database; that stays the API layer's job until Phase 5
teaches the graph itself how to pause for that human checkpoint.
"""
from arx.agents.a01_deal_screener import A01ValidationError, run_a01
from arx.agents.a02_underwriting_agent import A02ValidationError, run_a02
from arx.agents.a07_deal_memo_writer import A07ValidationError, run_a07
from arx.agents.a09_document_intelligence import A09ValidationError, run_a09
from arx.agents.errors import AgentValidationError
from arx.orchestration.state import DealGraphState


def _terminated(agent_id: str, exc: AgentValidationError) -> dict:
    return {
        "terminated": True,
        "termination_reason": f"{agent_id} validation failed: {exc}",
        "contradiction_flags": [{"agent_id": agent_id, "failed_checks": exc.failed_checks}],
    }


def a01_node(state: DealGraphState) -> dict:
    try:
        result = run_a01(
            deal_id=state["deal_id"],
            deal_type=state.get("deal_type"),
            property_address=state["property_address"],
            asking_price=state.get("asking_price"),
            unit_count=state.get("unit_count"),
            land_area_sf=state.get("land_area_sf"),
            current_gross_rent=state.get("current_gross_rent"),
            intended_use=state.get("intended_use"),
            target_cap_rate_range=state.get("target_cap_rate_range"),
            target_roc_range=state.get("target_roc_range"),
        )
    except A01ValidationError as exc:
        return _terminated("a01", exc)

    return {
        "deal_type": result.output.deal_type_detected,
        "agent_outputs": {**state.get("agent_outputs", {}), "a01": result.output.model_dump()},
    }


def a02_node(state: DealGraphState) -> dict:
    try:
        result = run_a02(
            gross_rent_hint=state.get("current_gross_rent"),
            purchase_price=state["purchase_price"],
            asset_type=state.get("asset_type", "multifamily"),
            submarket=state.get("submarket", state.get("property_address", "")),
            uw_defaults=state["uw_defaults"],
            loan_amount=state["loan_amount"],
            ltv=state["ltv"],
            interest_rate=state["interest_rate"],
            amortization_years=state["amortization_years"],
            comps=state.get("comps"),
        )
    except A02ValidationError as exc:
        return _terminated("a02", exc)

    return {"agent_outputs": {**state.get("agent_outputs", {}), "a02": result.output.model_dump()}}


def a07_node(state: DealGraphState) -> dict:
    a02_output = state.get("agent_outputs", {}).get("a02")
    if a02_output is None:
        raise ValueError("a07_node requires agent_outputs['a02'] to already be populated (R5)")

    try:
        result = run_a07(
            memo_track="development" if state.get("deal_type") == "development" else "acquisition",
            underwriting_snapshot=a02_output,
            confidence_score=a02_output.get("confidence_score", "low"),
            property_context={
                "address": state.get("property_address"), "asset_type": state.get("asset_type"),
                "unit_count": state.get("unit_count"), "land_area_sf": state.get("land_area_sf"),
            },
            audience_version=state.get("audience_version", "internal"),
        )
    except A07ValidationError as exc:
        return _terminated("a07", exc)

    return {"agent_outputs": {**state.get("agent_outputs", {}), "a07": result.output.model_dump()}}


def a09_node(state: DealGraphState) -> dict:
    pending = state.get("pending_document_ids", [])
    document = state.get("_current_document")  # {"document_type", "filename", "file_bytes" | "document_text"}
    if document is None:
        raise ValueError("a09_node requires state['_current_document'] to be set")

    try:
        result = run_a09(
            document_type=document["document_type"],
            filename=document["filename"],
            file_bytes=document.get("file_bytes"),
            document_text=document.get("document_text"),
            existing_underwriting_snapshot=state.get("agent_outputs", {}).get("a02"),
        )
    except A09ValidationError as exc:
        return _terminated("a09", exc)

    conflicts = state.get("document_extraction_conflicts", []) + [
        c.model_dump() for c in result.output.conflicts_detected
    ]
    return {
        "pending_document_ids": [d for d in pending if d != document.get("doc_id")],
        "document_extraction_conflicts": conflicts,
        "agent_outputs": {**state.get("agent_outputs", {}), "a09": result.output.model_dump()},
    }
