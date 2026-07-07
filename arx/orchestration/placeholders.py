"""Placeholder agent nodes. Section 07: Phase 1 has no agent logic. These stubs let the
graph topology in acquisition_flow.py / development_flow.py / document_flow.py be built
and tested now — edges, conditional routing, and state threading are all real — without
pretending an agent exists before Section 07's phase sequence says it should.

Each real agent module (arx/agents/a01_deal_screener.py, etc., landing per-phase
starting Section 07 Phase 2) replaces its corresponding placeholder here with a node
that: builds the prompt from /arx/prompts, calls the model, validates the schema
(Section 87), runs math validation where applicable (Section 15), writes a
deal_snapshot, and returns the updated DealGraphState. The graph wiring around it does
not change.
"""
from arx.orchestration.state import AgentId, DealGraphState


def placeholder_node(agent_id: AgentId, lands_in_phase: int):
    def _node(state: DealGraphState) -> DealGraphState:
        raise NotImplementedError(
            f"Agent '{agent_id}' has no logic yet — it lands in Phase {lands_in_phase} "
            f"(Section 07). This graph edge/topology is real; only the node body is a stub."
        )

    _node.__name__ = f"placeholder_{agent_id}"
    return _node
