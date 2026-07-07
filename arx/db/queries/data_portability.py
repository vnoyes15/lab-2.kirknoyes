"""Data Portability & Migration persistence — Section 74. Pairs with the pure
row-parsing/validation in arx/agents/data_portability.py: this module only does the
DB-side dedup lookup and insert per row, and the full-org export query.
"""
import csv
import io
import json

import psycopg
from psycopg.rows import dict_row

from arx.agents.data_portability import (
    parse_contact_row,
    parse_deal_performance_row,
    parse_deal_row,
    parse_lender_profile_row,
    parse_market_comp_row,
)


def _import_deal_row(conn: psycopg.Connection, *, org_id: str, row: dict) -> str:
    parsed = parse_deal_row(row)
    existing = conn.execute(
        "select deal_id from deals where org_id = %s and property_address = %s and status <> 'dead'",
        (org_id, parsed.property_address),
    ).fetchone()
    if existing is not None:
        return "duplicate"
    conn.execute(
        "insert into deals (org_id, property_address, source, deal_type, asking_price, unit_count, "
        "land_area_sf, asset_type) values (%s, %s, %s, %s, %s, %s, %s, %s)",
        (org_id, parsed.property_address, parsed.source, parsed.deal_type, parsed.asking_price,
         parsed.unit_count, parsed.land_area_sf, parsed.asset_type),
    )
    return "imported"


def _import_contact_row(conn: psycopg.Connection, *, org_id: str, row: dict) -> str:
    parsed = parse_contact_row(row)
    existing = conn.execute(
        "select contact_id from contacts where org_id = %s and name = %s and contact_category = %s",
        (org_id, parsed.name, parsed.contact_category),
    ).fetchone()
    if existing is not None:
        return "duplicate"
    contact_info = {k: v for k, v in {"email": parsed.email, "phone": parsed.phone}.items() if v is not None}
    conn.execute(
        "insert into contacts (org_id, name, contact_category, role_type, contact_info) "
        "values (%s, %s, %s, %s, %s)",
        (org_id, parsed.name, parsed.contact_category, parsed.role_type,
         json.dumps(contact_info) if contact_info else None),
    )
    return "imported"


def _import_market_comp_row(conn: psycopg.Connection, *, org_id: str, row: dict) -> str:
    parsed = parse_market_comp_row(row)
    existing = conn.execute(
        "select comp_id from market_comps where org_id = %s and submarket = %s "
        "and sale_date is not distinct from %s and source is not distinct from %s "
        "and cap_rate is not distinct from %s",
        (org_id, parsed.submarket, parsed.sale_date, parsed.source, parsed.cap_rate),
    ).fetchone()
    if existing is not None:
        return "duplicate"
    conn.execute(
        "insert into market_comps (org_id, submarket, asset_type, cap_rate, price_per_unit, sale_date, source) "
        "values (%s, %s, %s, %s, %s, %s, %s)",
        (org_id, parsed.submarket, parsed.asset_type, parsed.cap_rate, parsed.price_per_unit,
         parsed.sale_date, parsed.source),
    )
    return "imported"


def _import_lender_profile_row(conn: psycopg.Connection, *, org_id: str, row: dict) -> str:
    parsed = parse_lender_profile_row(row)
    contact = conn.execute(
        "select contact_id from contacts where org_id = %s and name = %s and contact_category = 'lender'",
        (org_id, parsed.contact_name),
    ).fetchone()
    if contact is None:
        contact_id = conn.execute(
            "insert into contacts (org_id, name, contact_category) values (%s, %s, 'lender') returning contact_id",
            (org_id, parsed.contact_name),
        ).fetchone()[0]
    else:
        contact_id = contact[0]
        existing_profile = conn.execute(
            "select lender_id from lender_profiles where contact_id = %s", (contact_id,)
        ).fetchone()
        if existing_profile is not None:
            return "duplicate"

    conn.execute(
        "insert into lender_profiles (contact_id, org_id, asset_types, loan_types, target_markets, "
        "ltv_max, ltc_max, dscr_threshold, last_deal_date, relationship_notes) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (contact_id, org_id, parsed.asset_types, parsed.loan_types, parsed.target_markets,
         parsed.ltv_max, parsed.ltc_max, parsed.dscr_threshold, parsed.last_deal_date, parsed.relationship_notes),
    )
    return "imported"


def _import_deal_performance_row(conn: psycopg.Connection, *, org_id: str, row: dict) -> str:
    parsed = parse_deal_performance_row(row)
    deal = conn.execute(
        "select deal_id from deals where org_id = %s and property_address = %s",
        (org_id, parsed.property_address),
    ).fetchone()
    if deal is None:
        raise ValueError(f"no deal found for property_address {parsed.property_address!r}")
    deal_id = deal[0]

    result = conn.execute(
        "insert into deal_performance (deal_id, org_id, period, actual_gross_rent, actual_vacancy_rate, "
        "actual_noi, actual_operating_expenses) values (%s, %s, %s, %s, %s, %s, %s) "
        "on conflict (deal_id, period) do nothing returning performance_id",
        (deal_id, org_id, parsed.period, parsed.actual_gross_rent, parsed.actual_vacancy_rate,
         parsed.actual_noi, parsed.actual_operating_expenses),
    ).fetchone()
    return "imported" if result is not None else "duplicate"


_ROW_IMPORTERS = {
    "deals": _import_deal_row,
    "contacts": _import_contact_row,
    "market_comps": _import_market_comp_row,
    "lender_profiles": _import_lender_profile_row,
    "deal_performance": _import_deal_performance_row,
}


def import_csv(conn: psycopg.Connection, *, org_id: str, resource_type: str, csv_text: str) -> dict:
    """Section 74: "Import validation: data type checks, deduplication against
    existing records, error report for failing rows. Failed rows do not block valid
    rows." Each row gets its own transaction-scoped savepoint so one bad row can't
    roll back rows already committed in this batch."""
    importer = _ROW_IMPORTERS[resource_type]
    reader = csv.DictReader(io.StringIO(csv_text))

    imported = 0
    duplicates = 0
    errors: list[dict] = []
    for row_number, row in enumerate(reader, start=2):  # header is row 1
        try:
            with conn.transaction():
                outcome = importer(conn, org_id=org_id, row=row)
        except (ValueError, psycopg.Error) as exc:
            errors.append({"row": row_number, "error": str(exc)})
            continue
        if outcome == "imported":
            imported += 1
        else:
            duplicates += 1

    return {"imported": imported, "duplicates_skipped": duplicates, "errors": errors}


_EXPORT_TABLES = (
    "deals", "financials", "deal_snapshots", "deal_status_history", "documents",
    "deal_performance", "contacts", "market_comps", "lender_profiles", "deal_tasks",
    "scenario_models", "equity_waterfalls",
)


def export_org_data(conn: psycopg.Connection, org_id: str) -> dict[str, list[dict]]:
    """Section 74: "All deal data, financial records, snapshots, documents, and
    performance history exportable... Operators own their data. Arx does not hold
    data hostage." Every table here is org-scoped directly by org_id — no join
    needed, since org_id is denormalized onto every one of them already."""
    export: dict[str, list[dict]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for table in _EXPORT_TABLES:
            cur.execute(f"select * from {table} where org_id = %s", (org_id,))  # noqa: S608 (table from fixed allowlist)
            export[table] = cur.fetchall()
    return export
