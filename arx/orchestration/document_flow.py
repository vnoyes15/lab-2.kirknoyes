"""Document-first flow — Section 04 R6, Section 67.

"When documents are attached, A-09 runs first. No other agent consumes data from a
document that A-09 has not processed" (R6). "Extraction conflicts require user
resolution before downstream agents run" (DI2).

A-09 itself lands in Phase 2 (Section 07) — this module wires the topology now so the
rule is structural (you cannot reach any other flow's first agent from here without
passing through this gate), not a convention agents are expected to remember.
"""
from langgraph.graph import END, START, StateGraph

from arx.orchestration.placeholders import placeholder_node
from arx.orchestration.state import DealGraphState


def route_after_extraction(state: DealGraphState) -> str:
    if state.get("document_extraction_conflicts"):
        # DI2 — halt for user resolution. Does not proceed to any downstream agent.
        return END
    return END  # Phase 1: no downstream flow to hand off to yet. Phase 2 wires this to
    # the acquisition/development flow's entry point once A-01/A-10 exist.


def build_document_flow() -> StateGraph:
    graph = StateGraph(DealGraphState)
    graph.add_node("a09", placeholder_node("a09", lands_in_phase=2))

    graph.add_edge(START, "a09")
    graph.add_conditional_edges("a09", route_after_extraction, {END: END})

    return graph


document_flow = build_document_flow().compile()
