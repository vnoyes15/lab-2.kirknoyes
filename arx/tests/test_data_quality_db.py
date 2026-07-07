"""Integration tests for Section 51 Data Quality Engine and Section 76 FL4 Feedback
Loop health reporting against a live Postgres + FastAPI app, plus their daily-brief
integration (Section 51's action items, Section 76 FL2's monthly-actuals prompt).
Skipped automatically if no DATABASE_URL is reachable.
"""
import time
from datetime import date

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from arx.api.config import get_settings
from arx.db.queries.daily_brief import build_daily_brief

try:
    settings = get_settings()
    _conn = psycopg.connect(settings.database_url, connect_timeout=3)
    _conn.close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="No reachable DATABASE_URL configured")


def _mint_token(org_id: str, role: str = "admin") -> str:
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
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_DATA_QUALITY_ORG', 500000) returning org_id"
        ).fetchone()[0])
        yield _org_id
    finally:
        if _org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (_org_id,))
        conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_stale_market_comps_flagged(client_and_token, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into market_comps (org_id, submarket, cap_rate, sale_date) "
        "values (%s, 'Tacoma', 0.06, current_date - 120)", (org_id,),
    )
    conn.execute(
        "insert into market_comps (org_id, submarket, cap_rate, sale_date) "
        "values (%s, 'Tacoma', 0.06, current_date - 10)", (org_id,),
    )
    conn.close()

    resp = client.get("/api/v1/data-quality/report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["stale_market_comps"]) == 1
    assert "market_intelligence" in body["market_intelligence_note"]


def test_stale_lender_profile_flagged(client_and_token, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    contact_id = conn.execute(
        "insert into contacts (org_id, name, contact_category) values (%s, 'Old Bank', 'lender') returning contact_id",
        (org_id,),
    ).fetchone()[0]
    conn.execute(
        "insert into lender_profiles (contact_id, org_id, created_at) "
        "values (%s, %s, now() - interval '400 days')", (contact_id, org_id),
    )
    conn.close()

    resp = client.get("/api/v1/data-quality/report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["stale_lender_profiles"]) == 1


def test_stale_active_snapshot_flagged(client_and_token, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    deal_id = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price) "
        "values (%s, '123 Main St', 'acquisition', 'underwriting', 5000000) returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.execute(
        "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, "
        "input_payload, output_payload, created_at) "
        "values (%s, %s, 'a02', 1, true, '{}'::jsonb, '{}'::jsonb, now() - interval '45 days')",
        (deal_id, org_id),
    )
    conn.close()

    resp = client.get("/api/v1/data-quality/report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["stale_active_snapshots"]) == 1


def test_a09_high_correction_rate_flagged(client_and_token, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    deal_id = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price) "
        "values (%s, '123 Main St', 'acquisition', 'underwriting', 5000000) returning deal_id",
        (org_id,),
    ).fetchone()[0]
    flags = ["inaccurate", "inaccurate", "accurate", "accurate"]
    for i, flag in enumerate(flags):
        conn.execute(
            "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, "
            "input_payload, output_payload, accuracy_flag) "
            "values (%s, %s, 'a09', %s, false, '{}'::jsonb, '{}'::jsonb, %s)",
            (deal_id, org_id, i + 1, flag),
        )
    conn.close()

    resp = client.get("/api/v1/data-quality/report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    flag_result = resp.json()["a09_high_correction_rate"]
    assert flag_result is not None
    assert flag_result["correction_rate"] == pytest.approx(0.5)
    assert flag_result["sample_size"] == 4


def test_missing_underwriting_snapshot_flagged_in_report_and_brief(client_and_token, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    deal_id = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price) "
        "values (%s, '123 Main St', 'acquisition', 'underwriting', 5000000) returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.close()

    resp = client.get("/api/v1/data-quality/report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    items = resp.json()["missing_required_fields_action_items"]
    assert any(i["deal_id"] == str(deal_id) and "A-02" in i["missing"] for i in items)

    brief_resp = client.get("/api/v1/brief", headers={"Authorization": f"Bearer {token}"})
    assert brief_resp.status_code == 200, brief_resp.text
    brief_items = brief_resp.json()["data_quality_action_items"]
    assert any(i["deal_id"] == str(deal_id) for i in brief_items)


def test_screened_deal_without_underwriting_not_flagged(client_and_token, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price) "
        "values (%s, '123 Main St', 'acquisition', 'screened', 5000000)", (org_id,),
    )
    conn.close()

    resp = client.get("/api/v1/data-quality/report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["missing_required_fields_action_items"] == []


def test_analyst_cannot_access_data_quality_report(org_id):
    from arx.api.main import app
    client = TestClient(app)
    analyst_token = _mint_token(org_id, "analyst")
    resp = client.get("/api/v1/data-quality/report", headers={"Authorization": f"Bearer {analyst_token}"})
    assert resp.status_code == 403


def test_feedback_loop_health_categorizes_owned_assets(client_and_token, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    current_deal = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price, is_acquired) "
        "values (%s, 'Current Asset', 'acquisition', 'closed', 5000000, true) returning deal_id",
        (org_id,),
    ).fetchone()[0]
    stale_deal = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price, is_acquired) "
        "values (%s, 'Stale Asset', 'acquisition', 'closed', 5000000, true) returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price, is_acquired) "
        "values (%s, 'No Data Asset', 'acquisition', 'closed', 5000000, true)", (org_id,),
    )
    conn.execute(
        "insert into deal_performance (deal_id, org_id, period, actual_noi) "
        "values (%s, %s, date_trunc('month', current_date)::date, 30000)", (current_deal, org_id),
    )
    conn.execute(
        "insert into deal_performance (deal_id, org_id, period, actual_noi) "
        "values (%s, %s, (date_trunc('month', current_date) - interval '3 months')::date, 30000)",
        (stale_deal, org_id),
    )
    conn.close()

    resp = client.get("/api/v1/feedback-loop/health", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_owned_assets"] == 3
    assert body["current"] == 1
    assert body["stale"] == 1
    assert body["no_data"] == 1


def test_monthly_actuals_prompt_only_appears_on_the_5th(org_id):
    from arx.api.main import app
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price, is_acquired) "
        "values (%s, 'Owned Asset', 'acquisition', 'closed', 5000000, true)", (org_id,),
    )
    conn.close()

    from arx.db.connection import db_session
    with db_session({"org_id": org_id, "role": "admin", "sub": "00000000-0000-0000-0000-0000000000aa"}) as conn:
        brief_on_5th = build_daily_brief(
            conn, org_id=org_id, user_id="00000000-0000-0000-0000-0000000000aa", role="admin",
            today=date(2026, 7, 5),
        )
        brief_off_day = build_daily_brief(
            conn, org_id=org_id, user_id="00000000-0000-0000-0000-0000000000aa", role="admin",
            today=date(2026, 7, 6),
        )

    assert len(brief_on_5th["monthly_actuals_prompt"]) == 1
    assert brief_off_day["monthly_actuals_prompt"] == []
