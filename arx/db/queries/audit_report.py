"""Audit & Compliance Report — Section 57.

"Complete chronological history of a deal: every agent output with inputs and
confidence score, every assumption and override, every status change, every document
uploaded, every counter-offer submitted, every human decision. A GP who can hand an LP
a complete, timestamped decision trail for every closed deal is a GP who gets invited
back for the next fund."

Every agent output means every deal_snapshots row for the deal (not just the active
one per agent — Section 13's immutability means a deactivated snapshot is still part
of the deal's real history, not something the audit trail should hide). Counter-offers
submitted are represented by A-12 Negotiation Support snapshots — A-12 is the agent
that logs a seller's counter and the response (Section 42), there's no separate
counter-offer table. "Human decisions" here covers accuracy flags (a human reviewed
and judged an output) and named scenarios modeled (a human chose to explore a
what-if) — snapshot *activation* itself has no separate history log (only current
is_active state is stored), a documented gap rather than a fabricated timeline.

Section 78 EP3: "error record visible in audit report." `errors` includes every
error_log row for the deal along with its resolution_status/resolution_notes (Section
78 EP2), so the trail shows not just that something failed but whether/how it was
resolved.
"""
import psycopg
from psycopg.rows import dict_row


def build_audit_report(conn: psycopg.Connection, deal_id: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select deal_id, property_address, deal_type, status from deals where deal_id = %s", (deal_id,))
        deal = cur.fetchone()
        if deal is None:
            return None

        cur.execute(
            "select agent_id, version_number, is_active, input_payload, output_payload, "
            "confidence_score, accuracy_flag, accuracy_note, created_by_user_id, created_at "
            "from deal_snapshots where deal_id = %s order by created_at",
            (deal_id,),
        )
        agent_outputs = cur.fetchall()

        cur.execute(
            "select input_field, input_value, assumption_type, financial_track, "
            "extraction_source, override_by_user_id, override_note, created_at "
            "from financials where deal_id = %s order by created_at",
            (deal_id,),
        )
        assumptions_and_overrides = cur.fetchall()

        cur.execute(
            "select status, entered_at, exited_at, changed_by_user_id "
            "from deal_status_history where deal_id = %s order by entered_at",
            (deal_id,),
        )
        status_changes = cur.fetchall()

        cur.execute(
            "select doc_id, doc_type, filename, version, uploaded_by, created_at "
            "from documents where deal_id = %s order by created_at",
            (deal_id,),
        )
        documents = cur.fetchall()

        cur.execute(
            "select scenario_name, assumption_overrides, created_by_user_id, created_at "
            "from scenario_models where deal_id = %s order by created_at",
            (deal_id,),
        )
        scenarios_modeled = cur.fetchall()

        cur.execute(
            "select error_id, error_type, agent_id, step, resolution_status, resolution_notes, created_at "
            "from error_log where deal_id = %s order by created_at",
            (deal_id,),
        )
        errors = cur.fetchall()

    counter_offers = [row for row in agent_outputs if row["agent_id"] == "a12"]
    accuracy_flags_set = [row for row in agent_outputs if row["accuracy_flag"] is not None]

    return {
        "deal_id": deal["deal_id"], "property_address": deal["property_address"],
        "deal_type": deal["deal_type"], "current_status": deal["status"],
        "agent_outputs": agent_outputs,
        "assumptions_and_overrides": assumptions_and_overrides,
        "status_changes": status_changes,
        "documents": documents,
        "counter_offers": counter_offers,
        "human_decisions": {
            "accuracy_flags_set": accuracy_flags_set,
            "scenarios_modeled": scenarios_modeled,
        },
        "errors": errors,
    }
