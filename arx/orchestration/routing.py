"""Routing rules — Section 04 R6/R7. Pure functions over DealGraphState so they're
testable today even though no agent exists yet to actually populate real outputs
(Section 07 Phase 1: "No agent logic yet").

These functions are what acquisition_flow.py / development_flow.py / document_flow.py
wire in as LangGraph conditional-edge callables once A-01 and A-09 land in Phase 2 —
the routing *decision* is separable from the agent that produces the inputs to it, so
it can be built and tested now.
"""
from typing import Literal

from arx.orchestration.state import AgentId, DealGraphState


def needs_document_processing(state: DealGraphState) -> bool:
    """R6: Document-first routing. When documents are attached, A-09 runs first. No
    other agent consumes data from a document A-09 has not processed."""
    return bool(state.get("pending_document_ids"))


def has_unresolved_extraction_conflicts(state: DealGraphState) -> bool:
    """Section 67 DI2: extraction conflicts require user resolution before downstream
    agents run — a populated conflict list halts the graph regardless of R6/R7 routing."""
    return bool(state.get("document_extraction_conflicts"))


def route_after_screening(state: DealGraphState) -> AgentId | Literal["end"]:
    """R7: Deal type routing. A-01 determines deal type.
        acquisition -> A-02
        land        -> A-10 (then A-11 on a land go/no-go of "pursue")
        development -> A-11 directly
    Requires A-01 to have already set state["deal_type"] and state["agent_outputs"]["a01"].
    """
    a01_output = state.get("agent_outputs", {}).get("a01")
    if a01_output is None:
        raise ValueError("route_after_screening called before A-01 produced an output")

    if a01_output.get("go_no_go") == "no_go":
        return "end"

    deal_type = state.get("deal_type")
    if deal_type == "acquisition":
        return "a02"
    if deal_type == "land":
        return "a10"
    if deal_type == "development":
        return "a11"
    raise ValueError(f"Unknown or unset deal_type: {deal_type!r}")


def route_after_land_screening(state: DealGraphState) -> AgentId | Literal["end"]:
    """R7 continued (Section 10 A-10 HANDOFF): land go -> A-11. Land go with a seller
    profile requested -> A-03 first, then A-11. No-go -> end."""
    a10_output = state.get("agent_outputs", {}).get("a10")
    if a10_output is None:
        raise ValueError("route_after_land_screening called before A-10 produced an output")

    recommendation = a10_output.get("routing_recommendation")
    if recommendation == "route_to_a11":
        return "a11"
    if recommendation == "route_to_a03_then_a11":
        return "a03"
    return "end"
