"""Real agent nodes for Phase 2 (A-01, A-02, A-07, A-09), Phase 3
(A-03, A-04, A-05, A-12), and Phase 4 (A-10, A-11).

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
from arx.agents.a03_seller_profiler import A03ValidationError, run_a03
from arx.agents.a04_offer_strategy import A04ValidationError, run_a04
from arx.agents.a05_loi_drafting import A05ValidationError, run_a05
from arx.agents.a07_deal_memo_writer import A07ValidationError, run_a07
from arx.agents.a09_document_intelligence import A09ValidationError, run_a09
from arx.agents.a10_land_acquisition import A10ValidationError, run_a10
from arx.agents.a11_development_pro_forma import A11ValidationError, run_a11
from arx.agents.a12_negotiation_support import A12ValidationError, run_a12
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


def a03_node(state: DealGraphState) -> dict:
    try:
        result = run_a03(
            deal_type=state.get("deal_type", "acquisition"),
            property_address=state["property_address"],
            owner_name=state.get("owner_name"),
            ownership_duration_years=state.get("ownership_duration_years"),
            public_record_data=state.get("public_record_data"),
            prior_contact_history=state.get("prior_contact_history"),
        )
    except A03ValidationError as exc:
        return _terminated("a03", exc)

    return {"agent_outputs": {**state.get("agent_outputs", {}), "a03": result.output.model_dump()}}


def a04_node(state: DealGraphState) -> dict:
    a02_output = state.get("agent_outputs", {}).get("a02")
    a03_output = state.get("agent_outputs", {}).get("a03")
    if a02_output is None:
        raise ValueError("a04_node requires agent_outputs['a02'] to already be populated (R5)")
    if a03_output is None:
        raise ValueError("a04_node requires agent_outputs['a03'] to already be populated")

    try:
        result = run_a04(
            deal_type=state.get("deal_type", "acquisition"),
            underwriting_snapshot=a02_output,
            seller_profile=a03_output,
            comps=state.get("comps"),
            feasibility_contingency_days_default=state.get("feasibility_contingency_days_default"),
        )
    except A04ValidationError as exc:
        return _terminated("a04", exc)

    return {"agent_outputs": {**state.get("agent_outputs", {}), "a04": result.output.model_dump()}}


def a05_node(state: DealGraphState) -> dict:
    a04_output = state.get("agent_outputs", {}).get("a04")
    if a04_output is None:
        raise ValueError("a05_node requires agent_outputs['a04'] to already be populated")
    # Section 04: "All three to user for selection. Selected strategy -> A-05" — the
    # human's selection is state["_selected_strategy_index"], not the whole array.
    selected_index = state.get("_selected_strategy_index", 0)
    selected_strategy = a04_output["strategies"][selected_index]

    try:
        result = run_a05(
            deal_type=state.get("deal_type", "acquisition"),
            state_code=state["state_code"],
            selected_offer_strategy=selected_strategy,
            org_jurisdiction=state["org_jurisdiction"],
            non_standard_structure=state.get("non_standard_structure"),
        )
    except A05ValidationError as exc:
        return _terminated("a05", exc)

    return {"agent_outputs": {**state.get("agent_outputs", {}), "a05": result.output.model_dump()}}


def a12_node(state: DealGraphState) -> dict:
    """Standalone — Section 42: A-12 only activates when a counter-offer is received,
    which is not a fixed next step after any other agent in this sequential flow. It
    has no place in counterparty_offer_flow.py's linear a03->a04->a05 topology; call
    this node directly (or via arx/api/agents.py's /agents/a12 endpoint) whenever a
    counter actually arrives, however much later that is."""
    a02_output = state.get("agent_outputs", {}).get("a02")
    if a02_output is None:
        raise ValueError("a12_node requires agent_outputs['a02'] to already be populated (R5)")

    try:
        result = run_a12(
            original_offer_strategy=state["original_offer_strategy"],
            seller_counter_terms=state["seller_counter_terms"],
            underwriting_snapshot=a02_output,
            seller_profile=state.get("agent_outputs", {}).get("a03"),
            comparable_precedents=state.get("comparable_precedents"),
            org_return_thresholds=state.get("org_return_thresholds"),
        )
    except A12ValidationError as exc:
        return _terminated("a12", exc)

    return {"agent_outputs": {**state.get("agent_outputs", {}), "a12": result.output.model_dump()}}


def a10_node(state: DealGraphState) -> dict:
    try:
        result = run_a10(
            property_address=state["property_address"],
            land_area_sf=state.get("land_area_sf"),
            asking_price=state.get("asking_price"),
            intended_use=state.get("intended_use"),
            zoning_info=state.get("zoning_info"),
            site_info=state.get("site_info"),
            owner_name=state.get("owner_name"),
            ownership_duration_years=state.get("ownership_duration_years"),
            entity_type=state.get("entity_type"),
            org_land_cost_per_unit_benchmark=state.get("org_land_cost_per_unit_benchmark"),
        )
    except A10ValidationError as exc:
        return _terminated("a10", exc)

    return {"agent_outputs": {**state.get("agent_outputs", {}), "a10": result.output.model_dump()}}


def a11_node(state: DealGraphState) -> dict:
    # A-11 runs either directly off an already-owned/entitled deal (route_after_screening's
    # "development" branch) or after A-10 has screened a raw land parcel (Section 04 R7).
    # In both cases the land cost is the deal's actual price, not A-10's per-unit estimate
    # (that estimate is a benchmark comparison, Section 87, not a substitute for the real
    # asking price) — so land_cost falls back to state["asking_price"] unless the caller
    # supplies an explicit override.
    land_cost = state.get("land_cost")
    if land_cost is None:
        land_cost = state.get("asking_price")

    try:
        result = run_a11(
            land_cost=land_cost,
            unit_count=state.get("unit_count"),
            asset_type=state.get("asset_type", "multifamily"),
            dev_defaults=state["dev_defaults"],
            exit_cap_rate=state["exit_cap_rate"],
            entitlement_context=state.get("entitlement_context"),
            rent_comps=state.get("rent_comps"),
        )
    except A11ValidationError as exc:
        return _terminated("a11", exc)

    return {"agent_outputs": {**state.get("agent_outputs", {}), "a11": result.output.model_dump()}}
