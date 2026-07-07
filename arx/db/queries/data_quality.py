"""Data Quality Engine persistence — Section 51. Pairs with the thresholds/pure
correction-rate math in arx/agents/data_quality.py the same way notifications.py
pairs with notification_rules.py.
"""
import psycopg
from psycopg.rows import dict_row

from arx.agents.data_quality import (
    A09_CORRECTION_RATE_THRESHOLD,
    ACTIVE_SNAPSHOT_STALE_DAYS,
    LENDER_PROFILES_STALE_DAYS,
    MARKET_COMPS_STALE_DAYS,
    a09_correction_rate,
)

# Acquisition deals past 'screened' need an active A-02 snapshot to proceed; land/
# development deals need an active A-11. A deal still at 'lead'/'screened' hasn't
# reached that stage yet, so it's not missing anything — and a 'closed'/'dead' deal
# has no "next stage" left to be missing fields for.
_ACQUISITION_POST_SCREEN_STATUSES = ("underwriting", "loi", "under_contract", "due_diligence")
_DEVELOPMENT_POST_SCREEN_STATUSES = (
    "loi", "under_contract", "due_diligence", "entitlement", "construction", "lease_up",
)


def get_stale_market_comps(conn: psycopg.Connection, org_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select comp_id, submarket, sale_date, created_at from market_comps "
            "where org_id = %s and coalesce(sale_date, created_at::date) < current_date - %s::int "
            "order by coalesce(sale_date, created_at::date)",
            (org_id, MARKET_COMPS_STALE_DAYS),
        )
        return cur.fetchall()


def get_stale_lender_profiles(conn: psycopg.Connection, org_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select lp.lender_id, c.name, lp.created_at from lender_profiles lp "
            "join contacts c on c.contact_id = lp.contact_id "
            "where lp.org_id = %s and lp.created_at < now() - (%s || ' days')::interval "
            "order by lp.created_at",
            (org_id, LENDER_PROFILES_STALE_DAYS),
        )
        return cur.fetchall()


def get_stale_active_snapshots(conn: psycopg.Connection, org_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select snapshot_id, deal_id, agent_id, created_at from deal_snapshots "
            "where org_id = %s and is_active = true and created_at < now() - (%s || ' days')::interval "
            "order by created_at",
            (org_id, ACTIVE_SNAPSHOT_STALE_DAYS),
        )
        return cur.fetchall()


def get_a09_high_correction_rate_flag(conn: psycopg.Connection, org_id: str) -> dict | None:
    """Section 51: "A-09 extraction records with high correction rates." Sampled over
    every a09 snapshot for the org regardless of age — the accuracy_flag is the
    correction signal, not the snapshot's own age (that's the separate stale-snapshot
    check above)."""
    row = conn.execute(
        "select accuracy_flag from deal_snapshots where org_id = %s and agent_id = 'a09'", (org_id,)
    ).fetchall()
    flags = [r[0] for r in row]
    rate = a09_correction_rate(flags)
    if rate is None or rate < A09_CORRECTION_RATE_THRESHOLD:
        return None
    return {"correction_rate": rate, "sample_size": len([f for f in flags if f is not None])}


def get_missing_required_fields_action_items(conn: psycopg.Connection, org_id: str) -> list[dict]:
    """"Missing required fields for next stage surface in daily brief as deal-specific
    action items." Interpreted concretely as: a deal has advanced past screening but
    has no active underwriting snapshot (A-02 for acquisition, A-11 for land/
    development) to support that stage — the next-stage-blocking gap an operator
    needs to act on."""
    items = []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, property_address, status from deals "
            "where org_id = %s and deal_type = 'acquisition' and status = any(%s) "
            "and not exists (select 1 from deal_snapshots s where s.deal_id = deals.deal_id "
            "and s.agent_id = 'a02' and s.is_active = true)",
            (org_id, list(_ACQUISITION_POST_SCREEN_STATUSES)),
        )
        for row in cur.fetchall():
            items.append({**row, "missing": "active A-02 underwriting snapshot"})

        cur.execute(
            "select deal_id, property_address, status from deals "
            "where org_id = %s and deal_type in ('land', 'development') and status = any(%s) "
            "and not exists (select 1 from deal_snapshots s where s.deal_id = deals.deal_id "
            "and s.agent_id = 'a11' and s.is_active = true)",
            (org_id, list(_DEVELOPMENT_POST_SCREEN_STATUSES)),
        )
        for row in cur.fetchall():
            items.append({**row, "missing": "active A-11 development pro forma snapshot"})

    return items


def run_data_quality_checks(conn: psycopg.Connection, org_id: str) -> dict:
    return {
        "stale_market_comps": get_stale_market_comps(conn, org_id),
        "stale_lender_profiles": get_stale_lender_profiles(conn, org_id),
        "market_intelligence_note": (
            "No market_intelligence table exists anywhere in this schema — not fabricated. "
            "Nothing else in the build brief defines what it would contain distinct from "
            "market_comps/market_signals."
        ),
        "stale_active_snapshots": get_stale_active_snapshots(conn, org_id),
        "a09_high_correction_rate": get_a09_high_correction_rate_flag(conn, org_id),
        "missing_required_fields_action_items": get_missing_required_fields_action_items(conn, org_id),
    }


def get_feedback_loop_health(conn: psycopg.Connection, org_id: str) -> dict:
    """Section 76 FL4: "Feedback loop quality is reported to Admin. Monthly: how many
    owned assets have current performance data, stale data, or no data." "current"
    means the asset has a deal_performance row for the current or immediately prior
    calendar month; "stale" means it has history but nothing that recent; "no_data"
    means zero deal_performance rows exist at all."""
    current_threshold = conn.execute(
        "select (date_trunc('month', current_date) - interval '1 month')::date"
    ).fetchone()[0]

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id from deals where org_id = %s and is_acquired = true", (org_id,)
        )
        owned_deal_ids = [r["deal_id"] for r in cur.fetchall()]

        current = stale = no_data = 0
        for deal_id in owned_deal_ids:
            cur.execute(
                "select max(period) as latest_period from deal_performance where deal_id = %s", (deal_id,)
            )
            latest_period = cur.fetchone()["latest_period"]
            if latest_period is None:
                no_data += 1
            elif latest_period >= current_threshold:
                current += 1
            else:
                stale += 1

    return {
        "total_owned_assets": len(owned_deal_ids),
        "current": current, "stale": stale, "no_data": no_data,
    }
