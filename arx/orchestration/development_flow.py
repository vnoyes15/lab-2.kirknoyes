"""Land / development flow — Section 07:
    Phase 2 A-01 Deal Screener routes land/development deals here (R7).
    Phase 4 adds A-10 Land Acquisition -> A-11 Development Pro Forma -> A-06 Due Diligence -> A-08 Outreach.

Land deals route A-01 -> A-10 -> A-11. Direct development deals (already-owned or
already-entitled land) route A-01 -> A-11 directly (Section 04 R7: "Development ->
A-11 directly"). A-03 Motivated Seller Profiler is invoked between A-10 and A-11 when
A-10 recommends it (Section 10 A-10 HANDOFF).
"""
from langgraph.graph import END, START, StateGraph

from arx.orchestration.nodes import a01_node, a03_node, a10_node, a11_node
from arx.orchestration.routing import route_after_land_screening, route_after_screening, route_unless_terminated
from arx.orchestration.state import DealGraphState


def build_development_flow() -> StateGraph:
    graph = StateGraph(DealGraphState)

    graph.add_node("a01", a01_node)  # real (Phase 2) — see arx/orchestration/nodes.py
    graph.add_node("a10", a10_node)  # real (Phase 4)
    graph.add_node("a03", a03_node)  # real (Phase 3)
    graph.add_node("a11", a11_node)  # real (Phase 4)

    graph.add_edge(START, "a01")
    graph.add_conditional_edges(
        "a01",
        route_after_screening,
        {"a02": END, "a10": "a10", "a11": "a11", "end": END},
        # a02 branch belongs to acquisition_flow.py, symmetric to that module's note.
    )

    graph.add_conditional_edges(
        "a10",
        route_after_land_screening,
        {"a11": "a11", "a03": "a03", "end": END},
    )
    graph.add_conditional_edges("a03", route_unless_terminated("a11"), {"a11": "a11", END: END})
    graph.add_edge("a11", END)

    return graph


development_flow = build_development_flow().compile()
