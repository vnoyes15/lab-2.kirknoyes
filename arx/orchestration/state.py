"""Shared orchestration state — Section 04 R1: "Maintain deal state. All agent
interactions on a deal link to one shared record."

This TypedDict is the LangGraph state object threaded through every flow in
acquisition_flow.py / development_flow.py / document_flow.py. Phase 1 has no agent
logic (Section 07) — this module exists so the state shape is fixed once, correctly,
before any agent is written against it, rather than getting bolted on ad hoc per agent
in Phase 2+.
"""
from typing import Literal, TypedDict

DealType = Literal["acquisition", "land", "development"]
AgentId = str  # "a01" .. "a13"


class DealGraphState(TypedDict, total=False):
    # R1 — identity, present on every node's view of the state.
    deal_id: str
    org_id: str
    deal_type: DealType | None  # None until A-01 sets it (R7)

    # R6 — document-first routing. Populated at intake; cleared as A-09 processes each
    # doc. No agent may consume deal data while this is non-empty (Section 04 R6,
    # Section 67 DI1).
    pending_document_ids: list[str]
    document_extraction_conflicts: list[dict]

    # R3 — clean handoffs. Each agent's full output is appended here for the next
    # agent's context; nobody re-collects information an earlier agent already produced.
    agent_outputs: dict[AgentId, dict]

    # R5 — active snapshot only. Keyed by agent_id -> the deal_snapshots.snapshot_id the
    # graph is allowed to read for that agent's output. Never "most recent automatically."
    active_snapshot_ids: dict[AgentId, str]

    # R2 — contradiction flags. An agent contradicting a prior agent's output on the same
    # deal must flag the discrepancy before proceeding; flags accumulate here.
    contradiction_flags: list[dict]

    # Routing / control.
    next_agent: AgentId | None
    terminated: bool
    termination_reason: str | None
