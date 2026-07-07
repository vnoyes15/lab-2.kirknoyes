"""Acquisition flow — Section 07 Phase 2 sequence:
    A-09 Document Intelligence -> A-01 Deal Screener -> A-02 Underwriting -> A-07 Deal Memo Writer

A-01/A-02/A-07 all land in Phase 2; this module wires the real topology (including the
R7 deal-type routing decision, which is genuine logic, not a stub) against placeholder
nodes so the shape doesn't need to be redesigned when the agents arrive.
"""
from langgraph.graph import END, START, StateGraph

from arx.orchestration.placeholders import placeholder_node
from arx.orchestration.routing import route_after_screening
from arx.orchestration.state import DealGraphState


def build_acquisition_flow() -> StateGraph:
    graph = StateGraph(DealGraphState)

    graph.add_node("a01", placeholder_node("a01", lands_in_phase=2))
    graph.add_node("a02", placeholder_node("a02", lands_in_phase=2))
    graph.add_node("a07", placeholder_node("a07", lands_in_phase=2))

    # R6 (document_flow.py) runs upstream of this graph's entry when documents are
    # attached at intake; A-01 is this flow's entry point either way.
    graph.add_edge(START, "a01")

    # R7 — real routing logic (arx/orchestration/routing.py), tested independently of
    # any agent existing yet.
    graph.add_conditional_edges(
        "a01",
        route_after_screening,
        {"a02": "a02", "a10": END, "a11": END, "end": END},
        # a10/a11 branches belong to development_flow.py — an acquisition-flow instance
        # reaching them would indicate A-01 misclassified deal_type; surfacing as END
        # here rather than silently cross-wiring into the other flow.
    )
    graph.add_edge("a02", "a07")
    graph.add_edge("a07", END)

    return graph


acquisition_flow = build_acquisition_flow().compile()
