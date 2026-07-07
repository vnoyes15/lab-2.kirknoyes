"""Network Intelligence Layer — Section 59.

"When multiple operators are on Arx and opt into anonymous data sharing, every
operator's intelligence improves... Double anonymization: org identity stripped
before writing to network_contributions. Zero PII, zero deal identifiers. Requires:
(1) org-level opt-in, (2) user explicit consent per contribution, (3) minimum 30-day
delay between deal close and contribution."

network_contributions retains org_id per-row (per its own migration's docstring) so a
contributing org can audit/manage its own history — the anonymization guarantee is
enforced at the *query* layer instead: contribute_deal_to_network only ever writes
non-identifying columns (submarket/asset_type/deal_type/cap_rate/price_per_unit/
financing_type/dd_days), and get_network_comps/get_network_status run over a
superuser connection (bypassing per-org RLS, the same documented carve-out
arx/tasks/momentum_scorer.py uses for cross-org jobs) specifically so they can
aggregate *across* orgs — but never select or return org_id in that aggregate output.

Only acquisition deals can contribute: network_contributions has no ROC/IRR columns,
so a development deal's closing economics have no home in this schema — a documented
scope boundary, not a silent gap.
"""
from datetime import date, timedelta

import psycopg
from psycopg.rows import dict_row

MIN_DAYS_SINCE_CLOSE = 30
NETWORK_TIER_THRESHOLDS = {"differentiated": 5, "most_accurate": 20}


class NetworkContributionError(Exception):
    pass


def _deal_closed_at(conn: psycopg.Connection, deal_id: str) -> date | None:
    row = conn.execute(
        "select entered_at from deal_status_history where deal_id = %s and status = 'closed' "
        "order by entered_at desc limit 1",
        (deal_id,),
    ).fetchone()
    if row is not None:
        return row[0].date()
    row = conn.execute(
        "select status_changed_at from deals where deal_id = %s and status = 'closed'", (deal_id,)
    ).fetchone()
    return row[0].date() if row is not None else None


def _dd_days(conn: psycopg.Connection, deal_id: str) -> int | None:
    row = conn.execute(
        "select entered_at, exited_at from deal_status_history "
        "where deal_id = %s and status = 'due_diligence' order by entered_at desc limit 1",
        (deal_id,),
    ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    return (row[1] - row[0]).days


def contribute_deal_to_network(
    conn: psycopg.Connection, *, org_id: str, deal_id: str, user_consent: bool, financing_type: str | None = None,
) -> str:
    if not user_consent:
        raise NetworkContributionError("User explicit consent is required per contribution (Section 59)")

    org_row = conn.execute("select network_participation from orgs where org_id = %s", (org_id,)).fetchone()
    if org_row is None or not org_row[0]:
        raise NetworkContributionError("Org has not opted in to network participation (Section 59)")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, deal_type, status, unit_count, submarket, asset_type "
            "from deals where deal_id = %s and org_id = %s",
            (deal_id, org_id),
        )
        deal = cur.fetchone()
    if deal is None:
        raise NetworkContributionError("Deal not found")
    if deal["status"] != "closed":
        raise NetworkContributionError("Only closed deals can contribute to the network")
    if deal["deal_type"] != "acquisition":
        raise NetworkContributionError(
            "Only acquisition deals can contribute — network_contributions has no ROC/IRR "
            "columns for development deal economics"
        )

    closed_at = _deal_closed_at(conn, deal_id)
    if closed_at is None or (date.today() - closed_at) < timedelta(days=MIN_DAYS_SINCE_CLOSE):
        raise NetworkContributionError(
            f"Deal must have been closed at least {MIN_DAYS_SINCE_CLOSE} days ago to contribute"
        )

    a02 = conn.execute(
        "select output_payload from deal_snapshots where deal_id = %s and agent_id = 'a02' and is_active = true",
        (deal_id,),
    ).fetchone()
    if a02 is None:
        raise NetworkContributionError("No active A-02 snapshot to source contribution data from")
    payload = a02[0]
    price_per_unit = (
        payload["purchase_price"] / deal["unit_count"] if deal["unit_count"] else None
    )

    row = conn.execute(
        """
        insert into network_contributions (org_id, submarket, asset_type, deal_type,
                                            close_cap_rate, price_per_unit, financing_type, dd_days)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        returning contribution_id
        """,
        (org_id, deal["submarket"], deal["asset_type"], deal["deal_type"],
         payload["cap_rate"], price_per_unit, financing_type, _dd_days(conn, deal_id)),
    ).fetchone()
    return str(row[0])


def _network_tier(contributing_org_count: int) -> str:
    if contributing_org_count >= NETWORK_TIER_THRESHOLDS["most_accurate"]:
        return "most_accurate"
    if contributing_org_count >= NETWORK_TIER_THRESHOLDS["differentiated"]:
        return "differentiated"
    return "below_threshold"


def get_network_status(superuser_conn: psycopg.Connection) -> dict:
    """Runs over a bypass-RLS connection so the distinct-org count spans every org on
    the platform, not just the caller's own — the count itself is the only thing
    surfaced, never which orgs they are."""
    row = superuser_conn.execute("select count(distinct org_id) from network_contributions").fetchone()
    contributing_org_count = row[0]
    return {"contributing_org_count": contributing_org_count, "tier": _network_tier(contributing_org_count)}


def get_network_comps(superuser_conn: psycopg.Connection, *, submarket: str, asset_type: str | None = None) -> dict:
    query = (
        "select count(*) as n, avg(close_cap_rate) as avg_cap_rate, avg(price_per_unit) as avg_price_per_unit "
        "from network_contributions where submarket = %s"
    )
    params: list = [submarket]
    if asset_type is not None:
        query += " and asset_type = %s"
        params.append(asset_type)
    with superuser_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        stats = cur.fetchone()

    status = get_network_status(superuser_conn)
    return {
        "submarket": submarket, "asset_type": asset_type,
        "contribution_count": stats["n"],
        "avg_cap_rate": float(stats["avg_cap_rate"]) if stats["avg_cap_rate"] is not None else None,
        "avg_price_per_unit": float(stats["avg_price_per_unit"]) if stats["avg_price_per_unit"] is not None else None,
        "network_tier": status["tier"],
    }
