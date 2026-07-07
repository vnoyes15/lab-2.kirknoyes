"""Integration tests for Section 44 Deal Risk Monitor and Section 45 Asset Performance
Tracking variance against a live Postgres + FastAPI app. Skipped automatically if no
DATABASE_URL is reachable.
"""
import json
import time

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from arx.api.config import get_settings

try:
    settings = get_settings()
    _conn = psycopg.connect(settings.database_url, connect_timeout=3)
    _conn.close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="No reachable DATABASE_URL configured")


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
        _org_id = str(conn.execute(
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_RISK_ORG', 500000) returning org_id"
        ).fetchone()[0])
        yield _org_id
    finally:
        if _org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (_org_id,))
        conn.close()


def _insert_deal(org_id: str, **overrides) -> str:
    conn = psycopg.connect(settings.database_url, autocommit=True)
    fields = {
        "org_id": org_id, "property_address": overrides.pop("property_address", "123 Main St"),
        "deal_type": "acquisition", "status": "lead", "asking_price": 5_000_000, "is_acquired": False,
    }
    fields.update(overrides)
    cols = ", ".join(fields)
    placeholders = ", ".join(f"%({k})s" for k in fields)
    row = conn.execute(
        f"insert into deals ({cols}) values ({placeholders}) returning deal_id", fields
    ).fetchone()
    conn.close()
    return str(row[0])


def _activate_a02_snapshot(org_id: str, deal_id: str, **overrides):
    fields = {
        "gross_rent": 500_000, "vacancy_rate": 0.07,
        "operating_expenses": {"management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
                                "insurance": 25_000, "taxes": 40_000, "other": 10_000},
        "noi": 300_000, "cap_rate": 0.06, "purchase_price": 5_000_000,
        "loan_amount": 3_750_000, "ltv": 0.75, "interest_rate": 0.065, "amortization_years": 30,
        "dscr": 1.35, "dscr_hard_fail": False, "dscr_warning": False, "cash_on_cash": 0.08,
    }
    fields.update(overrides)
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, "
        "input_payload, output_payload) values (%s, %s, 'a02', 1, true, '{}'::jsonb, %s::jsonb)",
        (deal_id, org_id, json.dumps(fields)),
    )
    conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_dscr_hard_fail_surfaces_as_critical_risk(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, status="underwriting")
    _activate_a02_snapshot(org_id, deal_id, dscr=0.9, dscr_hard_fail=True, dscr_warning=True)

    resp = client.get(f"/api/v1/deals/{deal_id}/risk", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    flags = resp.json()["risk_flags"]
    assert any(f["risk_type"] == "dscr_breach" and f["severity"] == "critical" for f in flags)


def test_healthy_deal_has_no_risk_flags(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, status="underwriting")
    _activate_a02_snapshot(org_id, deal_id)

    resp = client.get(f"/api/v1/deals/{deal_id}/risk", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["risk_flags"] == []


def test_risk_unknown_deal_404s(client_and_token):
    client, token = client_and_token
    resp = client.get(
        "/api/v1/deals/00000000-0000-0000-0000-000000000000/risk",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_dd_deadline_with_open_flags_risk(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, status="due_diligence")
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "update deals set days_in_current_status = 45 where deal_id = %s", (deal_id,)
    )
    conn.execute(
        "insert into deal_tasks (deal_id, org_id, title, status, priority, source_agent) "
        "values (%s, %s, 'DD: title', 'in_progress', 'high', 'a06')",
        (deal_id, org_id),
    )
    conn.close()

    resp = client.get(f"/api/v1/deals/{deal_id}/risk", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    flags = resp.json()["risk_flags"]
    assert any(f["risk_type"] == "dd_deadline_with_open_flags" for f in flags)


def test_portfolio_risk_monitor_only_returns_deals_with_flags(client_and_token, org_id):
    client, token = client_and_token
    risky_deal = _insert_deal(org_id, property_address="Risky Deal", status="underwriting")
    _activate_a02_snapshot(org_id, risky_deal, dscr=0.9, dscr_hard_fail=True, dscr_warning=True)
    healthy_deal = _insert_deal(org_id, property_address="Healthy Deal", status="underwriting")
    _activate_a02_snapshot(org_id, healthy_deal)

    resp = client.get("/api/v1/portfolio/risk-monitor", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    deal_ids = [d["deal_id"] for d in resp.json()]
    assert risky_deal in deal_ids
    assert healthy_deal not in deal_ids


def test_construction_budget_variance_and_draw_limit_risk(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(
        org_id, property_address="Dev Deal", deal_type="development", status="construction",
    )
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into construction_budget (deal_id, org_id, line_item, budget_amount, "
        "committed_amount, drawn_to_date, variance_amount) "
        "values (%s, %s, 'Framing', 1000000, 1000000, 950000, 150000)",
        (deal_id, org_id),
    )
    conn.close()

    resp = client.get(f"/api/v1/deals/{deal_id}/risk", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    risk_types = {f["risk_type"] for f in resp.json()["risk_flags"]}
    assert "budget_variance" in risk_types
    assert "construction_draw_approaching_limit" in risk_types


def test_performance_variance_notification_fires_above_threshold(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, status="closed", is_acquired=True)
    _activate_a02_snapshot(org_id, deal_id, noi=300_000)

    resp = client.post(
        f"/api/v1/deals/{deal_id}/performance",
        headers={"Authorization": f"Bearer {token}"},
        json={"period": "2026-07-01", "actual_noi": 200_000},  # -33% variance
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["variance_pct"] == pytest.approx(-1 / 3)

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select severity from notifications where org_id = %s and notification_type = 'performance_variance'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "critical"  # -33% exceeds the 20% Admin-escalation threshold


def test_performance_variance_below_threshold_no_notification(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, status="closed", is_acquired=True)
    _activate_a02_snapshot(org_id, deal_id, noi=300_000)

    resp = client.post(
        f"/api/v1/deals/{deal_id}/performance",
        headers={"Authorization": f"Bearer {token}"},
        json={"period": "2026-07-01", "actual_noi": 295_000},  # ~1.7% variance
    )
    assert resp.status_code == 201, resp.text

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'performance_variance'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 0


def test_performance_data_source_defaults_to_manual(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, status="closed", is_acquired=True)

    resp = client.post(
        f"/api/v1/deals/{deal_id}/performance",
        headers={"Authorization": f"Bearer {token}"},
        json={"period": "2026-07-01", "actual_noi": 30000},
    )
    assert resp.status_code == 201, resp.text

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute("select data_source from deal_performance where deal_id = %s", (deal_id,)).fetchone()
    conn.close()
    assert row[0] == "manual"
