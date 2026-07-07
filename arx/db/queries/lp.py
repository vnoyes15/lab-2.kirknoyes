"""LP Trust Layer — Section 49.

"LP Viewer role scoped to specific deals via deal_lp_access table. LP token can only
query records where their user_id is in deal_lp_access. Zero cross-deal visibility."

The functions here build a *curated* response — only ever the fields Section 49 names
as LP-visible. This is deliberately not a generic "fetch the deal, then filter" helper:
building the response as an explicit allow-list means a new column added to `deals`
later can never leak to an LP by accident, which a denylist approach would risk.
LP-hidden (never returned here): seller profiles, internal comments, assumption
overrides, offer strategy details.
"""
import re
from datetime import date

import psycopg
from psycopg.rows import dict_row

_QUARTER_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}


def parse_quarter_period(period: str) -> tuple[date, date]:
    """"Q1-2026" -> (2026-01-01, 2026-03-31). Section 49: GET .../report/{deal_id}?period=Q1-2026."""
    match = re.fullmatch(r"Q([1-4])-(\d{4})", period)
    if not match:
        raise ValueError(f"period must look like 'Q1-2026', got {period!r}")
    quarter, year = int(match.group(1)), int(match.group(2))
    start_month, end_month = _QUARTER_MONTHS[quarter]
    end_day = 30 if end_month in (4, 6, 9) else 31
    return date(year, start_month, 1), date(year, end_month, end_day)


def has_lp_access(conn: psycopg.Connection, *, deal_id: str, lp_user_id: str) -> bool:
    row = conn.execute(
        "select 1 from deal_lp_access where deal_id = %s and lp_user_id = %s",
        (deal_id, lp_user_id),
    ).fetchone()
    return row is not None


def list_lp_accessible_deals(conn: psycopg.Connection, lp_user_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select d.deal_id, d.property_address, d.deal_type, d.status
            from deals d
            inner join deal_lp_access a on a.deal_id = d.deal_id
            where a.lp_user_id = %s
            """,
            (lp_user_id,),
        )
        return cur.fetchall()


def _latest_investor_facing_memo(conn: psycopg.Connection, deal_id: str) -> dict | None:
    """Only the *active* A-07 snapshot is considered — Section 13's "downstream
    consumers always use the active snapshot" rule applies here too. If the active
    A-07 snapshot wasn't drafted for an investor audience, no memo is shown at all
    (never surface an internal-audience memo to an LP, even an old investor-facing one
    that's since been deactivated)."""
    row = conn.execute(
        "select output_payload, created_at from deal_snapshots "
        "where deal_id = %s and agent_id = 'a07' and is_active = true",
        (deal_id,),
    ).fetchone()
    if row is None:
        return None
    output_payload, created_at = row
    if output_payload.get("audience_version") != "investor_facing":
        return None
    return {"sections": output_payload.get("sections"), "generated_at": created_at.isoformat()}


def _material_activity_feed(conn: psycopg.Connection, deal_id: str) -> list[dict]:
    """"Material events" for LP purposes: status transitions and new investor-facing
    memos. Internal working activity (offer strategies drafted, DD tasks created,
    outreach sent) is deliberately excluded — none of it is LP-visible per Section 49."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select 'status_change' as event_type, status as detail, entered_at as occurred_at "
            "from deal_status_history where deal_id = %s "
            "union all "
            "select 'investor_memo_published' as event_type, agent_id as detail, created_at as occurred_at "
            "from deal_snapshots where deal_id = %s and agent_id = 'a07' "
            "and output_payload ->> 'audience_version' = 'investor_facing' "
            "order by occurred_at desc",
            (deal_id, deal_id),
        )
        return cur.fetchall()


def get_lp_deal_view(conn: psycopg.Connection, deal_id: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, property_address, deal_type, status from deals where deal_id = %s",
            (deal_id,),
        )
        deal = cur.fetchone()

        cur.execute(
            "select period, actual_gross_rent, actual_vacancy_rate, actual_noi, actual_operating_expenses "
            "from deal_performance where deal_id = %s order by period", (deal_id,),
        )
        performance_actuals = cur.fetchall()

    view = {
        "deal_id": deal["deal_id"], "property_address": deal["property_address"],
        "deal_type": deal["deal_type"], "status": deal["status"],
        "investor_facing_deal_memo": _latest_investor_facing_memo(conn, deal_id),
        "performance_actuals": performance_actuals,
        # Section 49 names this as LP-visible but no distribution-schedule model exists
        # yet anywhere in the platform — never fabricate a date there's no data for.
        "projected_distribution_dates": None,
        "activity_feed": _material_activity_feed(conn, deal_id),
    }

    if deal["deal_type"] in ("land", "development"):
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select milestone_type, projected_date, actual_date, status from development_milestones "
                "where deal_id = %s order by projected_date nulls last", (deal_id,),
            )
            milestones = cur.fetchall()
            cur.execute(
                "select coalesce(sum(budget_amount), 0) as budget, coalesce(sum(drawn_to_date), 0) as actual "
                "from construction_budget where deal_id = %s", (deal_id,),
            )
            budget_row = cur.fetchone()
            cur.execute(
                "select output_payload ->> 'return_on_cost' as roc from deal_snapshots "
                "where deal_id = %s and agent_id = 'a11' and is_active = true", (deal_id,),
            )
            a11_row = cur.fetchone()

        view["development"] = {
            "milestones": milestones,
            "construction_budget_summary": {"budget": budget_row["budget"], "actual_to_date": budget_row["actual"]},
            "roc_estimate_vs_underwriting_projection": float(a11_row["roc"]) if a11_row and a11_row["roc"] else None,
        }

    return view


def generate_lp_quarterly_report(conn: psycopg.Connection, *, deal_id: str, period: str) -> dict:
    """Section 49: "GET /api/v1/lp/report/{deal_id}?period=Q1-2026 generates structured
    LP quarterly report. Acquisition format: period performance, variance, capital
    account, upcoming events. Development format: milestone progress, budget status,
    timeline update."

    capital_account and upcoming_events are returned as None/empty with an explicit
    note, not fabricated — no capital-contributions/distributions ledger or scheduled-
    events model exists anywhere in the platform yet (Phase 6+ territory)."""
    start, end = parse_quarter_period(period)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, property_address, deal_type from deals where deal_id = %s", (deal_id,)
        )
        deal = cur.fetchone()

        cur.execute(
            "select period, actual_gross_rent, actual_vacancy_rate, actual_noi, actual_operating_expenses "
            "from deal_performance where deal_id = %s and period between %s and %s order by period",
            (deal_id, start, end),
        )
        period_performance = cur.fetchall()

    report = {
        "deal_id": deal["deal_id"], "property_address": deal["property_address"],
        "period": period, "period_start": start.isoformat(), "period_end": end.isoformat(),
    }

    if deal["deal_type"] in ("land", "development"):
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select milestone_type, projected_date, actual_date, status from development_milestones "
                "where deal_id = %s order by projected_date nulls last", (deal_id,),
            )
            milestones = cur.fetchall()
            cur.execute(
                "select coalesce(sum(budget_amount), 0) as budget, coalesce(sum(drawn_to_date), 0) as actual, "
                "coalesce(sum(variance_amount), 0) as variance from construction_budget where deal_id = %s",
                (deal_id,),
            )
            budget = cur.fetchone()
        report["format"] = "development"
        report["milestone_progress"] = milestones
        report["budget_status"] = budget
        report["timeline_update"] = next(
            (m for m in milestones if m["milestone_type"] == "stabilization"), None
        )
    else:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select output_payload ->> 'noi' as projected_noi from deal_snapshots "
                "where deal_id = %s and agent_id = 'a02' and is_active = true", (deal_id,),
            )
            a02_row = cur.fetchone()
        projected_noi = float(a02_row["projected_noi"]) if a02_row and a02_row["projected_noi"] else None
        actual_noi = period_performance[-1]["actual_noi"] if period_performance else None
        report["format"] = "acquisition"
        report["period_performance"] = period_performance
        report["variance"] = {
            "projected_noi": projected_noi, "actual_noi": actual_noi,
            "variance_pct": (
                round((float(actual_noi) - projected_noi) / projected_noi * 100, 1)
                if projected_noi and actual_noi is not None else None
            ),
        }
        report["capital_account"] = None
        report["upcoming_events"] = []

    return report
