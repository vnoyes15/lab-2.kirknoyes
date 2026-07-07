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

    # Deal facts fed to A-01/A-02 (Section 87 inputs) — populated by whoever invokes
    # the graph (Phase 2: arx/api/agents.py reads these from the deals/uw_config
    # tables; Phase 5's autonomous graph would populate them itself).
    property_address: str
    asking_price: float | None
    unit_count: int | None
    land_area_sf: float | None
    current_gross_rent: float | None
    intended_use: str | None
    target_cap_rate_range: tuple[float, float] | None
    target_roc_range: tuple[float, float] | None

    purchase_price: float
    asset_type: str
    submarket: str
    uw_defaults: dict
    loan_amount: float
    ltv: float
    interest_rate: float
    amortization_years: int
    comps: list[dict] | None

    audience_version: str

    # A-09 (arx/orchestration/nodes.py:a09_node) processes one document per node
    # invocation; the caller sets this before running the node.
    _current_document: dict | None

    # Phase 3 — Counterparty + Offer Layer (Section 07). A-03/A-04/A-05 inputs; a12 is
    # a separate on-demand re-entry point (Section 42: only activates when a counter
    # is received), not part of this sequential flow — see counterparty_offer_flow.py.
    owner_name: str | None
    ownership_duration_years: float | None
    public_record_data: dict | None
    prior_contact_history: dict | None

    feasibility_contingency_days_default: int | None

    state_code: str
    org_jurisdiction: dict
    non_standard_structure: str | None
    # Which of A-04's 3 strategies (index 0/1/2) the human selected for A-05 to draft.
    _selected_strategy_index: int

    # A-12 inputs (standalone — see arx/orchestration/nodes.py:a12_node docstring).
    original_offer_strategy: dict
    seller_counter_terms: dict
    comparable_precedents: list[dict] | None
    org_return_thresholds: dict | None
