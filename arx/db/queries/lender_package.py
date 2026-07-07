"""Lender Package Generation — Section 71.

"GET /api/v1/deals/{id}/lender-package generates a lender-ready submission package in
one action. Package includes: A-07 deal memo, A-02 or A-11 underwriting output, rent
roll summary, property inspection summary, title commitment summary, environmental
summary, ZONIQ operating track record, capital stack structure. What currently
requires hours of manual assembly takes one action."

Every section here is assembled from data that already exists elsewhere in the
platform — this module does no new computation, it only gathers. The one section with
no real source is "ZONIQ operating track record": nothing anywhere in this schema
tracks a fund-level historical performance record (portfolio_summary tracks *current*
owned-asset performance, not a track-record narrative across closed funds) — returned
as None with an explicit note rather than fabricated, same pattern as the LP quarterly
report's capital_account gap (arx/db/queries/lp.py).
"""
import psycopg
from psycopg.rows import dict_row


def _latest_a09_extraction(conn: psycopg.Connection, deal_id: str, document_type: str) -> dict | None:
    """A-09 snapshots for different document types on the same deal aren't mutually
    exclusive the way a02/a11 versions are (uq_deal_snapshots_active is one active a09
    row per deal, not per document type) — so this looks at every a09 snapshot
    regardless of is_active and picks the most recent extraction of the requested
    type, rather than relying on "the" active a09 snapshot."""
    row = conn.execute(
        """
        select output_payload from deal_snapshots
        where deal_id = %s and agent_id = 'a09' and output_payload ->> 'document_type_detected' = %s
        order by created_at desc limit 1
        """,
        (deal_id, document_type),
    ).fetchone()
    if row is None:
        return None
    payload = row[0]
    return {
        "extraction_completeness": payload["extraction_completeness"],
        "extracted_fields": {k: v["value"] for k, v in payload["extracted_fields"].items()},
        "missing_required_fields": payload["missing_required_fields"],
    }


def _capital_stack(conn: psycopg.Connection, deal_id: str, deal_type: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select waterfall_id, structure_type, outputs from equity_waterfalls "
            "where deal_id = %s order by created_at desc limit 1",
            (deal_id,),
        )
        latest_waterfall = cur.fetchone()

    if deal_type == "acquisition":
        row = conn.execute(
            "select output_payload from deal_snapshots "
            "where deal_id = %s and agent_id = 'a02' and is_active = true",
            (deal_id,),
        ).fetchone()
        if row is not None:
            payload = row[0]
            stack = {
                "senior_debt": payload["loan_amount"], "equity": payload["purchase_price"] * (1 - payload["ltv"]),
                "ltv": payload["ltv"], "interest_rate": payload["interest_rate"],
            }
        else:
            stack = None
    else:
        row = conn.execute(
            "select output_payload from deal_snapshots "
            "where deal_id = %s and agent_id = 'a11' and is_active = true",
            (deal_id,),
        ).fetchone()
        stack = {"total_project_cost": row[0]["total_project_cost"]} if row is not None else None

    if stack is not None and latest_waterfall is not None:
        outputs = latest_waterfall["outputs"]
        stack["equity_structure"] = {
            "structure_type": latest_waterfall["structure_type"],
            "lp_capital": outputs.get("lp_capital"), "gp_capital": outputs.get("gp_capital"),
        }

    return stack


def build_lender_package(conn: psycopg.Connection, deal_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, property_address, deal_type, status from deals where deal_id = %s", (deal_id,),
        )
        deal = cur.fetchone()
    if deal is None:
        return None

    memo_row = conn.execute(
        "select output_payload from deal_snapshots "
        "where deal_id = %s and agent_id = 'a07' and is_active = true",
        (deal_id,),
    ).fetchone()

    underwriting_agent = "a02" if deal["deal_type"] == "acquisition" else "a11"
    underwriting_row = conn.execute(
        "select output_payload from deal_snapshots "
        "where deal_id = %s and agent_id = %s and is_active = true",
        (deal_id, underwriting_agent),
    ).fetchone()

    return {
        "deal_id": deal["deal_id"], "property_address": deal["property_address"],
        "deal_type": deal["deal_type"], "status": deal["status"],
        "deal_memo": memo_row[0] if memo_row is not None else None,
        "underwriting_output": {
            "agent_id": underwriting_agent, "output": underwriting_row[0] if underwriting_row is not None else None,
        },
        "rent_roll_summary": _latest_a09_extraction(conn, deal_id, "rent_roll"),
        "property_inspection_summary": _latest_a09_extraction(conn, deal_id, "inspection"),
        "title_commitment_summary": _latest_a09_extraction(conn, deal_id, "title_commitment"),
        "environmental_summary": _latest_a09_extraction(conn, deal_id, "environmental"),
        "operating_track_record": None,
        "operating_track_record_note": (
            "No fund-level historical track-record data source exists in this platform yet — "
            "not fabricated. Portfolio summary (Section 29) tracks current owned-asset "
            "performance but not a track-record narrative across closed funds."
        ),
        "capital_stack": _capital_stack(conn, deal_id, deal["deal_type"]),
    }
