"""Counterparty + Offer flow — Section 07 Phase 3:
    A-03 Seller Profiler (with land archetypes) -> A-04 Offer Strategy -> A-05 LOI Drafting

A-12 Negotiation Support is deliberately NOT chained into this graph — see
arx/orchestration/nodes.py:a12_node's docstring for why (Section 42: it only
activates later, when a counter-offer actually arrives, not as a fixed next step
here). Same scope boundary as acquisition_flow.py: this graph is real and exercised
in tests, but arx/api/agents.py's per-agent endpoints remain the Phase 3 production
path, since A-04's "all three [strategies] to user for selection" step is exactly the
kind of human checkpoint that requires LangGraph's interrupt/resume support to model
properly in-graph (Phase 5 scope, not Phase 3).
"""
from langgraph.graph import END, START, StateGraph

from arx.orchestration.nodes import a03_node, a04_node, a05_node
from arx.orchestration.routing import route_unless_terminated
from arx.orchestration.state import DealGraphState


def build_counterparty_offer_flow() -> StateGraph:
    graph = StateGraph(DealGraphState)

    graph.add_node("a03", a03_node)
    graph.add_node("a04", a04_node)
    graph.add_node("a05", a05_node)

    graph.add_edge(START, "a03")
    # Conditional, not a plain add_edge: an a03/a04 validation failure sets
    # state["terminated"] (arx/orchestration/nodes.py's _terminated()) and must halt
    # here rather than falling through into a node whose required input never arrived.
    graph.add_conditional_edges("a03", route_unless_terminated("a04"), {"a04": "a04", END: END})
    graph.add_conditional_edges("a04", route_unless_terminated("a05"), {"a05": "a05", END: END})
    graph.add_edge("a05", END)

    return graph


counterparty_offer_flow = build_counterparty_offer_flow().compile()
