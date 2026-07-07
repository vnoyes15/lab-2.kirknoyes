"""Portfolio Layer — Section 29.

"Once a deal closes (is_acquired = true), it enters the portfolio layer. deal_performance
records monthly actuals. Portfolio layer aggregates across all owned assets — both
acquisitions and stabilized development projects. Development pipeline view shows
milestone status, construction budget variance, projected stabilization date, and
current ROC estimate."
"""
import psycopg
from psycopg.rows import dict_row

from arx.agents.portfolio_stress import (
    StressParams,
    stress_acquisition_asset,
    stress_development_asset,
    summarize_portfolio_stress,
)


def record_deal_performance(
    conn: psycopg.Connection, *,
    deal_id: str, org_id: str, period: str, actual_gross_rent: float | None,
    actual_vacancy_rate: float | None, actual_noi: float | None,
    actual_operating_expenses: float | None, notes: str | None, created_by_user_id: str | None,
    data_source: str = "manual",
) -> str:
    row = conn.execute(
        """
        insert into deal_performance (deal_id, org_id, period, actual_gross_rent,
                                       actual_vacancy_rate, actual_noi, actual_operating_expenses,
                                       notes, created_by_user_id, data_source)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (deal_id, period) do update set
            actual_gross_rent = excluded.actual_gross_rent,
            actual_vacancy_rate = excluded.actual_vacancy_rate,
            actual_noi = excluded.actual_noi,
            actual_operating_expenses = excluded.actual_operating_expenses,
            notes = excluded.notes,
            created_by_user_id = excluded.created_by_user_id,
            data_source = excluded.data_source
        returning performance_id
        """,
        (deal_id, org_id, period, actual_gross_rent, actual_vacancy_rate,
         actual_noi, actual_operating_expenses, notes, created_by_user_id, data_source),
    ).fetchone()
    return str(row[0])


def get_active_a02_noi(conn: psycopg.Connection, deal_id: str) -> float | None:
    """Section 45: "System calculates actual NOI vs. projected from active A-02
    snapshot at acquisition." Returns None if the deal has no active A-02 snapshot —
    variance simply can't be computed yet, not an error."""
    row = conn.execute(
        "select output_payload ->> 'noi' as noi from deal_snapshots "
        "where deal_id = %s and agent_id = 'a02' and is_active = true",
        (deal_id,),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def list_deal_performance(conn: psycopg.Connection, deal_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select * from deal_performance where deal_id = %s order by period", (deal_id,)
        )
        return cur.fetchall()


def get_portfolio_summary(conn: psycopg.Connection, org_id: str) -> dict:
    """Aggregates across every owned asset (is_acquired = true), acquisition and
    stabilized-development alike — Section 29 doesn't distinguish the two once a deal
    is owned."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, property_address, deal_type, asset_type, asking_price, "
            "acquisition_date, status from deals where org_id = %s and is_acquired = true",
            (org_id,),
        )
        assets = cur.fetchall()

        cur.execute(
            """
            select dp.deal_id, dp.actual_noi
            from deal_performance dp
            inner join (
                select deal_id, max(period) as max_period
                from deal_performance where org_id = %s group by deal_id
            ) latest on latest.deal_id = dp.deal_id and latest.max_period = dp.period
            """,
            (org_id,),
        )
        latest_noi_by_deal = {row["deal_id"]: row["actual_noi"] for row in cur.fetchall()}

    for asset in assets:
        asset["latest_actual_noi"] = latest_noi_by_deal.get(asset["deal_id"])

    total_latest_noi = sum(v for v in latest_noi_by_deal.values() if v is not None)
    return {
        "asset_count": len(assets),
        "total_latest_monthly_noi": total_latest_noi,
        "assets": assets,
    }


def get_development_pipeline(conn: psycopg.Connection, org_id: str) -> list[dict]:
    """Section 29: "Development pipeline view shows milestone status, construction
    budget variance, projected stabilization date, and current ROC estimate." Covers
    every development/land deal not yet closed or dead — including ones that haven't
    entered construction yet, since milestone status itself (e.g. "entitlement still
    pending") is exactly what an operator needs to see before construction starts."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, property_address, status from deals "
            "where org_id = %s and deal_type in ('land', 'development') and status not in ('closed', 'dead')",
            (org_id,),
        )
        deals = cur.fetchall()

        for deal in deals:
            cur.execute(
                "select milestone_type, projected_date, actual_date, status, variance_days "
                "from development_milestones where deal_id = %s order by projected_date nulls last",
                (deal["deal_id"],),
            )
            deal["milestones"] = cur.fetchall()

            cur.execute(
                "select coalesce(sum(variance_amount), 0) as total_variance "
                "from construction_budget where deal_id = %s",
                (deal["deal_id"],),
            )
            deal["construction_budget_variance"] = cur.fetchone()["total_variance"]

            stabilization = next(
                (m for m in deal["milestones"] if m["milestone_type"] == "stabilization"), None
            )
            deal["projected_stabilization_date"] = stabilization["projected_date"] if stabilization else None

            cur.execute(
                "select output_payload ->> 'return_on_cost' as roc from deal_snapshots "
                "where deal_id = %s and agent_id = 'a11' and is_active = true",
                (deal["deal_id"],),
            )
            a11_row = cur.fetchone()
            deal["current_roc_estimate"] = float(a11_row["roc"]) if a11_row and a11_row["roc"] else None

    return deals


def run_portfolio_stress_test(conn: psycopg.Connection, org_id: str, params: StressParams) -> dict:
    """Section 47. Every owned asset (is_acquired = true) is stressed: acquisition
    deals against their active A-02 snapshot, development deals still in construction
    (not yet stabilized/closed/dead) against their active A-11 snapshot. A deal with
    neither an active A-02 nor A-11 snapshot has nothing to stress and is skipped —
    that's an active-snapshot gap the daily brief / data quality checks surface
    separately, not something this endpoint should silently pretend to model."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, property_address, deal_type, status from deals "
            "where org_id = %s and is_acquired = true",
            (org_id,),
        )
        owned = cur.fetchall()

        stressed_assets = []
        for deal in owned:
            if deal["deal_type"] in ("land", "development") and deal["status"] != "stabilized":
                cur.execute(
                    "select output_payload from deal_snapshots "
                    "where deal_id = %s and agent_id = 'a11' and is_active = true",
                    (deal["deal_id"],),
                )
                snapshot = cur.fetchone()
                if snapshot is None:
                    continue
                result = stress_development_asset(baseline=snapshot["output_payload"], params=params)
            else:
                cur.execute(
                    "select output_payload from deal_snapshots "
                    "where deal_id = %s and agent_id = 'a02' and is_active = true",
                    (deal["deal_id"],),
                )
                snapshot = cur.fetchone()
                if snapshot is None:
                    continue
                result = stress_acquisition_asset(baseline=snapshot["output_payload"], params=params)

            result["deal_id"] = deal["deal_id"]
            result["property_address"] = deal["property_address"]
            stressed_assets.append(result)

    summary = summarize_portfolio_stress(stressed_assets)
    summary["assets"] = stressed_assets
    summary["params"] = {
        "interest_rate_shock_bps": params.interest_rate_shock_bps,
        "vacancy_shock_bps": params.vacancy_shock_bps,
        "cap_rate_expansion_bps": params.cap_rate_expansion_bps,
    }
    return summary
