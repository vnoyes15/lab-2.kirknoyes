"""Acquisition flow — Section 07 Phase 2 sequence:
    A-09 Document Intelligence -> A-01 Deal Screener -> A-02 Underwriting -> A-07 Deal Memo Writer

A-01/A-02/A-07 all land in Phase 2 and are wired here as real nodes
(arx/orchestration/nodes.py) — see that module's docstring for the scope boundary on
what this graph is (and isn't yet) used for in production.

Phase 5 (Section 07 "full state management, handoffs") adds a checkpointed variant,
acquisition_flow_with_checkpoint, that actually pauses at the a02->a07 boundary rather
than just running straight through — see the docstring below the plain
acquisition_flow definition for why there are two, and arx/orchestration/nodes.py's
scope-boundary docstring for why arx/api/agents.py, not either of these, remains the
real production invocation path.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from arx.orchestration.nodes import a01_node, a02_node, a07_node
from arx.orchestration.routing import route_after_screening
from arx.orchestration.state import DealGraphState


def build_acquisition_flow() -> StateGraph:
    graph = StateGraph(DealGraphState)

    graph.add_node("a01", a01_node)
    graph.add_node("a02", a02_node)
    graph.add_node("a07", a07_node)

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

# Section 13/R5: "New snapshot never auto-activates — user designates explicitly...
# Downstream agents always use the active snapshot." acquisition_flow (above) runs
# a02->a07 straight through in one call, which is correct for the in-memory tests that
# use it (there's no real deal_snapshots row or activation step involved at all) but
# does NOT model R5's human checkpoint. acquisition_flow_with_checkpoint does: compiled
# with interrupt_before=["a07"] and a checkpointer, invoking it with a thread_id runs
# a01->a02 and then genuinely pauses — a07 will not run until a second, explicit
# .invoke(None, same thread_id) call resumes it, exactly mirroring "a02 writes an
# inactive snapshot, a human activates it via a separate API call, only then can a07
# proceed" (see arx/tests/test_orchestration_interrupt_resume.py).
#
# MemorySaver is an in-process, non-persistent checkpointer — correct for proving the
# pause/resume mechanics and for this graph's existing "in-memory testing scaffold"
# role (see arx/orchestration/nodes.py), but a real deployment pausing a graph across
# separate HTTP requests (possibly hours or days apart, per R5) needs a persistent
# checkpointer. langgraph-checkpoint-postgres is the natural swap — deliberately not
# added here: as of this writing it forces langgraph-checkpoint>=4.0, which conflicts
# with this project's pinned langgraph==0.2.62 (which requires <3.0.0). Upgrading both
# together is a real dependency-compatibility project, not a drop-in swap; tracked here
# rather than silently forced in.
acquisition_flow_with_checkpoint = build_acquisition_flow().compile(
    checkpointer=MemorySaver(), interrupt_before=["a07"],
)
