#!/usr/bin/env python3
"""Seed the ZONIQ org — Section 86, S6.

"Creates ZONIQ org record, sets default uw_config for both tracks, initializes
org_jurisdictions for WA with rent control defaults from Section 18. Copy the
DEFAULT_ORG_ID output to .env."

This is a platform-bootstrap script, not a request handler — it connects directly
with the DATABASE_URL / service-role connection and intentionally bypasses RLS
(there is no authenticated org session yet; this is what creates the first one).
Never model application code after this pattern (see arx/db/connection.py).

Idempotent: safe to re-run. Looks up the org by name before inserting, and only
inserts a jurisdiction row if that (org_id, state_code) pair doesn't already exist.
"""
import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

ZONIQ_ORG_NAME = "ZONIQ"

# Section 04 (ZONIQ DEFAULTS) / Section 02.
ACQUISITION_DEFAULTS = {
    "vacancy": 0.07,
    "property_management": 0.08,
    "maintenance": 0.05,
    "capex_reserves": 0.05,
    "insurance_pct_of_price": 0.005,
    "ltv": 0.75,
    "interest_rate": 0.065,
    "amortization_years": 30,
}

# Section 10 (A-11 KEY DEFAULTS).
DEVELOPMENT_DEFAULTS = {
    "soft_costs_pct_of_hard_min": 0.15,
    "soft_costs_pct_of_hard_max": 0.20,
    "construction_contingency_pct_min": 0.05,
    "construction_contingency_pct_max": 0.10,
    "construction_loan_ltc": 0.65,
    "stabilized_occupancy": 0.93,
}

# Section 18 — WA rent control (RCW 59.18, effective May 2025). These are the only
# jurisdiction figures the build brief actually specifies (Section 84 market reference).
WA_JURISDICTION = {
    "state_code": "WA",
    "earnest_money_pct": 0.01,
    "earnest_money_holder": "licensed_escrow",
    "acquisition_dd_days": 30,
    "land_feasibility_days_min": 60,
    "land_feasibility_days_max": 90,
    "closing_timeline_days_min": 45,
    "closing_timeline_days_max": 60,
    "rent_control_active": True,
    "rent_control_cap_formula": "7% + CPI, or 10%, whichever is lower",
    "rent_control_notice_days": 90,
    "attorney_review_required": True,
    "notes": "RCW 59.18 amendment, effective May 2025. NOT LEGAL ADVICE (Section 18) — "
             "ZONIQ's attorney must review before use in any real transaction.",
}

# Section 56: "WA, CA, OR pre-populated with rent control parameters." The brief gives
# exact figures only for WA (Section 18/84). CA and OR are seeded with the same
# structural (non-rent-control) defaults and rent_control_active=true (Section 84 notes
# WA is "third state after CA and OR"), but their cap/notice figures are left null
# rather than fabricated — N3's "never fabricate data" applies to this scaffold too.
# Fill these in from counsel before any CA/OR deal is underwritten.
OTHER_PREPOPULATED_JURISDICTIONS = [
    {
        "state_code": "CA",
        "earnest_money_pct": 0.01,
        "earnest_money_holder": "licensed_escrow",
        "acquisition_dd_days": 30,
        "land_feasibility_days_min": 60,
        "land_feasibility_days_max": 90,
        "closing_timeline_days_min": 45,
        "closing_timeline_days_max": 60,
        "rent_control_active": True,
        "rent_control_cap_formula": None,
        "rent_control_notice_days": None,
        "attorney_review_required": True,
        "notes": "Rent control parameters not specified in build brief — confirm with "
                 "counsel (AB 1482 Tenant Protection Act) before underwriting CA deals.",
    },
    {
        "state_code": "OR",
        "earnest_money_pct": 0.01,
        "earnest_money_holder": "licensed_escrow",
        "acquisition_dd_days": 30,
        "land_feasibility_days_min": 60,
        "land_feasibility_days_max": 90,
        "closing_timeline_days_min": 45,
        "closing_timeline_days_max": 60,
        "rent_control_active": True,
        "rent_control_cap_formula": None,
        "rent_control_notice_days": None,
        "attorney_review_required": True,
        "notes": "Rent control parameters not specified in build brief — confirm with "
                 "counsel (SB 608) before underwriting OR deals.",
    },
]


def seed(database_url: str, token_budget_monthly_default: int) -> str:
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("select org_id from orgs where org_name = %s", (ZONIQ_ORG_NAME,))
            row = cur.fetchone()
            if row:
                org_id = row[0]
                print(f"ZONIQ org already exists: {org_id}")
            else:
                cur.execute(
                    """
                    insert into orgs (org_name, token_budget_monthly, network_participation, status)
                    values (%s, %s, false, 'active')
                    returning org_id
                    """,
                    (ZONIQ_ORG_NAME, token_budget_monthly_default),
                )
                org_id = cur.fetchone()[0]
                print(f"Created ZONIQ org: {org_id}")

            for track, defaults in (("acquisition", ACQUISITION_DEFAULTS), ("development", DEVELOPMENT_DEFAULTS)):
                cur.execute(
                    "select 1 from uw_config where org_id = %s and track = %s and is_active",
                    (org_id, track),
                )
                if cur.fetchone():
                    print(f"  uw_config[{track}] already active, skipping")
                    continue
                cur.execute(
                    """
                    insert into uw_config (org_id, track, version, is_active, config)
                    values (%s, %s, 1, true, %s)
                    """,
                    (org_id, track, json.dumps(defaults)),
                )
                print(f"  Seeded uw_config[{track}] v1")

            for jurisdiction in [WA_JURISDICTION, *OTHER_PREPOPULATED_JURISDICTIONS]:
                cur.execute(
                    "select 1 from org_jurisdictions where org_id = %s and state_code = %s",
                    (org_id, jurisdiction["state_code"]),
                )
                if cur.fetchone():
                    print(f"  org_jurisdictions[{jurisdiction['state_code']}] already exists, skipping")
                    continue
                cur.execute(
                    """
                    insert into org_jurisdictions (
                        org_id, state_code, earnest_money_pct, earnest_money_holder,
                        acquisition_dd_days, land_feasibility_days_min, land_feasibility_days_max,
                        closing_timeline_days_min, closing_timeline_days_max,
                        rent_control_active, rent_control_cap_formula, rent_control_notice_days,
                        attorney_review_required, notes
                    ) values (
                        %(org_id)s, %(state_code)s, %(earnest_money_pct)s, %(earnest_money_holder)s,
                        %(acquisition_dd_days)s, %(land_feasibility_days_min)s, %(land_feasibility_days_max)s,
                        %(closing_timeline_days_min)s, %(closing_timeline_days_max)s,
                        %(rent_control_active)s, %(rent_control_cap_formula)s, %(rent_control_notice_days)s,
                        %(attorney_review_required)s, %(notes)s
                    )
                    """,
                    {"org_id": org_id, **jurisdiction},
                )
                print(f"  Seeded org_jurisdictions[{jurisdiction['state_code']}]")

    return str(org_id)


if __name__ == "__main__":
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set.")

    token_budget = int(os.environ.get("TOKEN_BUDGET_MONTHLY_DEFAULT", "500000"))
    org_id = seed(database_url, token_budget)

    print()
    print("=" * 60)
    print(f"DEFAULT_ORG_ID={org_id}")
    print("Copy the line above into your .env (development only — Section 86: "
          "never set DEFAULT_ORG_ID in production).")
    print("=" * 60)
