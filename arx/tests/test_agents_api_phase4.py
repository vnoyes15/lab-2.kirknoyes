"""Integration tests for the Phase 4 API endpoints (A-10, A-11, A-06, A-08) against a
live Postgres + FastAPI app. Skipped automatically if no DATABASE_URL is reachable.
As in test_agents_api_phase3.py, the real Anthropic client is never constructed —
every test overrides model_client_dependency with a FakeModelClient.
"""
import json
import time

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from arx.agents.a06_due_diligence import ACQUISITION_CATEGORIES
from arx.agents.model_client import model_client_dependency
from arx.api.config import get_settings
from arx.tests.fakes import FakeModelClient

try:
    settings = get_settings()
    _conn = psycopg.connect(settings.database_url, connect_timeout=3)
    _conn.close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="No reachable DATABASE_URL configured")

LAND_COST = 1_000_000
HARD_COSTS = 6_000_000
SOFT_COSTS = 1_200_000
FINANCING_COSTS = 300_000
CONTINGENCY = 500_000
TOTAL_PROJECT_COST = LAND_COST + HARD_COSTS + SOFT_COSTS + FINANCING_COSTS + CONTINGENCY
STABILIZED_NOI = 720_000
RETURN_ON_COST = STABILIZED_NOI / TOTAL_PROJECT_COST
EXIT_CAP_RATE = 0.06
DEVELOPMENT_SPREAD = RETURN_ON_COST - EXIT_CAP_RATE
EQUITY = 3_000_000
PAYOFF = EQUITY * (1.20 ** 3)


def _mint_token(org_id: str, role: str = "analyst") -> str:
    return jwt.encode(
        {"sub": "00000000-0000-0000-0000-0000000000aa", "org_id": org_id, "role": role, "exp": int(time.time()) + 3600},
        settings.secret_key, algorithm="HS256",
    )


@pytest.fixture
def org_id():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    _org_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_PHASE4_ORG', 500000) returning org_id"
            )
            _org_id = str(cur.fetchone()[0])
        yield _org_id
    finally:
        if _org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (_org_id,))
        conn.close()


@pytest.fixture
def land_deal_id(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        row = conn.execute(
            "insert into deals (org_id, property_address, deal_type, asset_type, asking_price, land_area_sf) "
            "values (%s, 'Vacant lot, Auburn WA', 'land', 'land', 800000, 40000) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def deal_id(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        row = conn.execute(
            "insert into deals (org_id, property_address, deal_type, asset_type, asking_price, unit_count) "
            "values (%s, '123 Main St, Tacoma WA', 'acquisition', 'multifamily', 5000000, 24) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def contact_id(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        row = conn.execute(
            "insert into contacts (org_id, name, contact_category) values (%s, 'J. Smith', 'seller') returning contact_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def suppressed_contact_id(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        row = conn.execute(
            "insert into contacts (org_id, name, contact_category, suppressed, suppressed_at) "
            "values (%s, 'Do Not Contact', 'seller', true, now()) returning contact_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def _override_model(fake):
    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    return app


def _clear_override():
    from arx.api.main import app
    app.dependency_overrides.pop(model_client_dependency, None)


# --------------------------------------------------------------------------- A-10 ---

def test_invoke_a10_pursue_recommendation(client_and_token, land_deal_id):
    client, token = client_and_token
    fake = FakeModelClient({
        "feasibility_recommendation": "pursue", "entitlement_path": "by_right",
        "site_risk_flags": [], "seller_archetype": "long_hold", "routing_recommendation": "route_to_a11",
        "confidence_score": "medium", "estimated_developable_units": 32,
        "estimated_land_cost_per_unit": 25_000, "entitlement_timeline_estimate_months": 4,
        "land_cost_benchmark_comparison": "In line with the org's $25,000/unit benchmark.",
    })
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{land_deal_id}/agents/a10",
            headers={"Authorization": f"Bearer {token}"},
            json={"intended_use": "multifamily", "zoning_info": {"zone": "R-3", "by_right": True}},
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text
    assert resp.json()["output"]["routing_recommendation"] == "route_to_a11"


# --------------------------------------------------------------------------- A-11 ---

def _a11_response(**overrides):
    base = {
        "total_project_cost": TOTAL_PROJECT_COST,
        "cost_breakdown": {
            "land_cost": LAND_COST, "hard_costs": HARD_COSTS, "soft_costs": SOFT_COSTS,
            "financing_costs": FINANCING_COSTS, "contingency": CONTINGENCY,
        },
        "stabilized_noi": STABILIZED_NOI, "return_on_cost": RETURN_ON_COST, "exit_cap_rate": EXIT_CAP_RATE,
        "development_spread": DEVELOPMENT_SPREAD, "value_destructive": False,
        "cash_flows": [-EQUITY, 0, 0, PAYOFF], "irr": 0.20,
        "construction_draw_schedule": [
            {"period": "Q1", "draw_amount": 1_800_000, "cumulative_drawn": 1_800_000},
            {"period": "Q2", "draw_amount": 1_800_000, "cumulative_drawn": 3_600_000},
            {"period": "Q3", "draw_amount": 1_800_000, "cumulative_drawn": 5_400_000},
            {"period": "Q4", "draw_amount": 1_800_000, "cumulative_drawn": 7_200_000},
        ],
        "cost_overrun_sensitivity": {
            "base": {"return_on_cost": 0.08}, "cost_overrun_5pct": {"return_on_cost": 0.076},
            "cost_overrun_10pct": {"return_on_cost": 0.072}, "cost_overrun_15pct": {"return_on_cost": 0.068},
        },
        "absorption_delay_sensitivity": {
            "base": {"return_on_cost": 0.08}, "absorption_delay_3mo": {"return_on_cost": 0.078},
            "absorption_delay_6mo": {"return_on_cost": 0.075},
        },
        "risk_flags": [
            "entitlement:conditional use permit still pending city council vote",
            "construction_cost:steel pricing has been volatile in this market",
            "absorption:two comparable projects are delivering units in the same window",
            "financing:construction loan rate lock expires before permits are expected",
        ],
        "confidence_score": {"overall": "medium", "entitlement_confidence": "medium", "construction_cost_confidence": "high"},
    }
    base.update(overrides)
    return base


def test_invoke_a11_without_active_dev_config_409s(client_and_token, land_deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{land_deal_id}/agents/a11",
        headers={"Authorization": f"Bearer {token}"},
        json={"land_cost": LAND_COST, "unit_count": 32, "exit_cap_rate": EXIT_CAP_RATE},
    )
    assert resp.status_code == 409


def test_invoke_a11_with_active_dev_config_succeeds(client_and_token, land_deal_id, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into uw_config (org_id, track, version, is_active, config) values (%s, 'development', 1, true, %s)",
        (org_id, json.dumps({"soft_costs_pct_of_hard_min": 0.15, "soft_costs_pct_of_hard_max": 0.20})),
    )
    conn.close()

    fake = FakeModelClient(_a11_response())
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{land_deal_id}/agents/a11",
            headers={"Authorization": f"Bearer {token}"},
            json={"land_cost": LAND_COST, "unit_count": 32, "exit_cap_rate": EXIT_CAP_RATE},
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["output"]["value_destructive"] is False
    assert body["validation"]["passed"] is True


# --------------------------------------------------------------------------- A-06 ---

def _item(category, status="complete", flag_note=None):
    return {
        "item_id": category, "category": category, "description": f"{category} review",
        "why_it_matters": "Standard due diligence for this deal.",
        "responsible_party": "buyer's attorney", "status": status,
        "flag_note": flag_note, "assigned_user_id": None,
    }


def test_invoke_a06_creates_deal_tasks(client_and_token, deal_id):
    client, token = client_and_token
    fake = FakeModelClient({
        "dd_track": "acquisition",
        "checklist_items": [_item(c) for c in ACQUISITION_CATEGORIES],
        "wa_rent_compliance_item": None,
    })
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a06",
            headers={"Authorization": f"Bearer {token}"},
            json={"dd_track": "acquisition", "deal_facts": {"asset_type": "multifamily"}},
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["output"]["deal_advancement_blocked"] is False
    assert len(body["output"]["tasks_created"]) == len(ACQUISITION_CATEGORIES)

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute("select count(*) from deal_tasks where deal_id = %s", (deal_id,)).fetchone()
    conn.close()
    assert row[0] == len(ACQUISITION_CATEGORIES)


def test_invoke_a06_flagged_item_sets_high_priority_task(client_and_token, deal_id):
    client, token = client_and_token
    items = [_item(c) for c in ACQUISITION_CATEGORIES]
    items[0] = _item(ACQUISITION_CATEGORIES[0], status="flagged", flag_note="Title report shows an unresolved lien from 2019.")
    fake = FakeModelClient({"dd_track": "acquisition", "checklist_items": items, "wa_rent_compliance_item": None})
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a06",
            headers={"Authorization": f"Bearer {token}"},
            json={"dd_track": "acquisition"},
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text
    assert resp.json()["output"]["deal_advancement_blocked"] is True

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from deal_tasks where deal_id = %s and priority = 'high'", (deal_id,)
    ).fetchone()
    conn.close()
    assert row[0] == 1


# --------------------------------------------------------------------------- A-08 ---

def _a08_response(**overrides):
    base = {
        "message_text": "Hi, I'm reaching out about a potential acquisition in your area. " * 2,
        "channel": "email", "can_spam_placeholder": "[SENDER PHYSICAL ADDRESS]",
    }
    base.update(overrides)
    return base


def test_invoke_a08_success_logs_outreach_and_updates_contact(client_and_token, deal_id, contact_id):
    client, token = client_and_token
    fake = FakeModelClient(_a08_response())
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a08",
            headers={"Authorization": f"Bearer {token}"},
            json={"contact_id": contact_id, "recipient_type": "seller", "channel": "email"},
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute("select count(*) from outreach_log where contact_id = %s", (contact_id,)).fetchone()
    contact_row = conn.execute(
        "select last_contacted_at from contacts where contact_id = %s", (contact_id,)
    ).fetchone()
    conn.close()
    assert row[0] == 1
    assert contact_row[0] is not None


def test_invoke_a08_suppressed_contact_403s(client_and_token, deal_id, suppressed_contact_id):
    client, token = client_and_token
    fake = FakeModelClient(_a08_response())
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a08",
            headers={"Authorization": f"Bearer {token}"},
            json={"contact_id": suppressed_contact_id, "recipient_type": "seller", "channel": "email"},
        )
    finally:
        _clear_override()
    assert resp.status_code == 403
    assert len(fake.calls) == 0


def test_invoke_a08_unknown_contact_404s(client_and_token, deal_id):
    client, token = client_and_token
    fake = FakeModelClient(_a08_response())
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a08",
            headers={"Authorization": f"Bearer {token}"},
            json={"contact_id": "00000000-0000-0000-0000-000000000000", "recipient_type": "seller", "channel": "email"},
        )
    finally:
        _clear_override()
    assert resp.status_code == 404


def test_invoke_a08_daily_limit_reached_429s(client_and_token, deal_id, contact_id, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    other_contact = conn.execute(
        "insert into contacts (org_id, name, contact_category) values (%s, 'Bulk Target', 'broker') returning contact_id",
        (org_id,),
    ).fetchone()[0]
    with conn.transaction():
        for _ in range(50):
            conn.execute(
                "insert into outreach_log (org_id, contact_id, recipient_type, channel, message_text) "
                "values (%s, %s, 'broker', 'email', %s)",
                (org_id, other_contact, "x" * 150),
            )
    conn.close()

    fake = FakeModelClient(_a08_response())
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a08",
            headers={"Authorization": f"Bearer {token}"},
            json={"contact_id": contact_id, "recipient_type": "seller", "channel": "email"},
        )
    finally:
        _clear_override()
    assert resp.status_code == 429
    assert len(fake.calls) == 0
