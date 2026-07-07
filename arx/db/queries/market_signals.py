"""Market Signal Processing — Section 62.

"Signal-to-deal impact routing: When a market_signals record is created with
significance = high, the system queries all active deals in the affected submarket.
For each affected deal: recalculates relevant metrics, writes deal_id to
market_signals.deal_impacts, triggers deal risk monitor notification. Operators do
not have to monitor market conditions and check which deals they affect."

Signal sourcing itself (fed funds rate feeds, BLS employment data, permit activity
feeds) is Phase 6 external-data-integration scope this environment has no
credentials for (same documented gap as interest-rate/market-comp feeds elsewhere) —
market_signals rows are entered manually (Phase 1 baseline per the table's own
migration comment) via the API below; the routing logic that runs once a signal
exists is the real, implementable part of this section.

"Recalculates relevant metrics" is implemented as a momentum-score recompute for
every affected deal (arx/db/queries/pipeline.py::recalculate_org_momentum) — the one
existing, safe, non-model-invoking "recompute this deal's metrics" mechanism in the
platform. Re-running A-02/A-11 themselves would mean a market signal silently
triggering new AI-generated snapshots with no human in the loop, which Section 13's
"snapshots are never auto-created without a request" discipline rules out.
"""
import json

import psycopg
from psycopg.rows import dict_row

from arx.agents.notification_rules import market_signal_deal_impact_notification
from arx.db.queries.pipeline import recalculate_org_momentum
from arx.notifications.channels import InAppChannel


def create_market_signal(
    conn: psycopg.Connection, *, org_id: str, signal_type: str, submarket: str | None,
    signal_value: float, prior_value: float | None, source: str | None, significance: str | None,
) -> str:
    change_pct = (signal_value - prior_value) / prior_value if prior_value else None
    row = conn.execute(
        """
        insert into market_signals (org_id, signal_type, submarket, signal_value, prior_value,
                                     change_pct, source, significance)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        returning signal_id
        """,
        (org_id, signal_type, submarket, signal_value, prior_value, change_pct, source, significance),
    ).fetchone()
    return str(row[0])


def route_signal_to_deals(conn: psycopg.Connection, *, org_id: str, signal_id: str) -> list[str]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select signal_id, signal_type, submarket, significance, change_pct "
            "from market_signals where signal_id = %s and org_id = %s",
            (signal_id, org_id),
        )
        signal = cur.fetchone()
    if signal is None or signal["significance"] != "high" or not signal["submarket"]:
        return []

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, property_address from deals "
            "where org_id = %s and submarket = %s and status not in ('closed', 'dead')",
            (org_id, signal["submarket"]),
        )
        affected_deals = cur.fetchall()
    if not affected_deals:
        return []

    affected_deal_ids = [str(d["deal_id"]) for d in affected_deals]
    conn.execute(
        "update market_signals set deal_impacts = %s where signal_id = %s",
        (json.dumps(affected_deal_ids), signal_id),
    )

    recalculate_org_momentum(conn, org_id)

    channel = InAppChannel()
    for deal in affected_deals:
        spec = market_signal_deal_impact_notification(
            property_address=deal["property_address"], signal_type=signal["signal_type"],
            submarket=signal["submarket"], change_pct=signal["change_pct"],
        )
        channel.send(conn, org_id=org_id, spec=spec, deal_id=str(deal["deal_id"]))

    return affected_deal_ids


def list_market_signals(conn: psycopg.Connection, org_id: str, submarket: str | None = None) -> list[dict]:
    query = "select * from market_signals where org_id = %s"
    params: list = [org_id]
    if submarket is not None:
        query += " and submarket = %s"
        params.append(submarket)
    query += " order by observed_at desc"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()
