"""Integration tests for pipeline view + momentum scoring against a live Postgres +
FastAPI app. Skipped automatically if no DATABASE_URL is reachable — same pattern as
test_relationship_warmth_db.py / test_agents_api_phase4.py.
"""
import time
from datetime import timedelta

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from arx.api.config import get_settings
from arx.db.queries.pipeline import recalculate_org_momentum

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
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_PIPELINE_ORG', 500000) returning org_id"
            )
            _org_id = str(cur.fetchone()[0])
        yield _org_id
    finally:
        if _org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (_org_id,))
        conn.close()


def _insert_deal(org_id: str, status: str = "lead", **overrides) -> str:
    conn = psycopg.connect(settings.database_url, autocommit=True)
    fields = {
        "org_id": org_id, "property_address": overrides.pop("property_address", f"Deal at {status}"),
        "deal_type": "acquisition", "status": status, "asking_price": 1_000_000,
    }
    fields.update(overrides)
    cols = ", ".join(fields)
    placeholders = ", ".join(f"%({k})s" for k in fields)
    row = conn.execute(
        f"insert into deals ({cols}) values ({placeholders}) returning deal_id", fields
    ).fetchone()
    conn.close()
    return str(row[0])


def test_recalculate_org_momentum_scores_fresh_deal_high(org_id):
    deal_id = _insert_deal(org_id, status="underwriting")
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        recalculate_org_momentum(conn, org_id)
        row = conn.execute(
            "select momentum_score, days_in_current_status from deals where deal_id = %s", (deal_id,)
        ).fetchone()
    finally:
        conn.close()
    # A brand-new deal (status_changed_at ~ now, no activity yet) — recency contributes
    # 0 (no snapshots/outreach/tasks exist), status-duration penalty is 0 (0 days in
    # status) — net momentum is 0, not None (status isn't terminal).
    assert row[0] == 0
    assert row[1] == 0


def test_recalculate_org_momentum_skips_terminal_deals(org_id):
    dead_deal = _insert_deal(org_id, status="dead", close_reason_code="other")
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        n = recalculate_org_momentum(conn, org_id)
        row = conn.execute("select momentum_score from deals where deal_id = %s", (dead_deal,)).fetchone()
    finally:
        conn.close()
    assert n == 0
    assert row[0] is None


def test_recalculate_org_momentum_uses_recent_task_activity(org_id):
    deal_id = _insert_deal(org_id, status="due_diligence")
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_tasks (deal_id, org_id, title, status) values (%s, %s, 'Title review', 'not_started')",
        (deal_id, org_id),
    )
    try:
        recalculate_org_momentum(conn, org_id)
        row = conn.execute("select momentum_score from deals where deal_id = %s", (deal_id,)).fetchone()
    finally:
        conn.close()
    # A task created "now" counts as fresh activity -> top recency bucket, 0 status
    # duration penalty (deal just entered due_diligence) -> full 100.
    assert row[0] == 100


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_pipeline_view_orders_by_stage_then_momentum(client_and_token, org_id):
    client, token = client_and_token
    loi_deal = _insert_deal(org_id, status="loi", property_address="LOI stage deal")
    lead_deal = _insert_deal(org_id, status="lead", property_address="Lead stage deal")
    dead_deal = _insert_deal(org_id, status="dead", property_address="Dead deal", close_reason_code="other")

    resp = client.get("/api/v1/pipeline", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    deal_ids = [d["deal_id"] for d in body]
    assert lead_deal in deal_ids
    assert loi_deal in deal_ids
    assert dead_deal not in deal_ids  # dead deals excluded from the active pipeline view

    lead_index = deal_ids.index(lead_deal)
    loi_index = deal_ids.index(loi_deal)
    assert lead_index < loi_index  # 'lead' precedes 'loi' in Section 23's stage order


def test_pipeline_view_requires_auth(client_and_token):
    client, _ = client_and_token
    resp = client.get("/api/v1/pipeline")
    assert resp.status_code in (401, 403)


def test_pipeline_view_status_filter_includes_dead(client_and_token, org_id):
    client, token = client_and_token
    dead_deal = _insert_deal(org_id, status="dead", property_address="Dead deal", close_reason_code="other")
    lead_deal = _insert_deal(org_id, status="lead", property_address="Lead deal")

    resp = client.get("/api/v1/pipeline?status=dead", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    deal_ids = [d["deal_id"] for d in resp.json()]
    assert dead_deal in deal_ids
    assert lead_deal not in deal_ids


def test_pipeline_view_filters_by_deal_type_and_submarket(client_and_token, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    land_deal = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, submarket) "
        "values (%s, 'Land parcel', 'land', 'lead', 'tacoma') returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.close()
    acq_deal = _insert_deal(org_id, status="lead", property_address="Acquisition deal", submarket="seattle")

    resp = client.get("/api/v1/pipeline?deal_type=land", headers={"Authorization": f"Bearer {token}"})
    deal_ids = [d["deal_id"] for d in resp.json()]
    assert str(land_deal) in deal_ids
    assert acq_deal not in deal_ids

    resp = client.get("/api/v1/pipeline?submarket=seattle", headers={"Authorization": f"Bearer {token}"})
    deal_ids = [d["deal_id"] for d in resp.json()]
    assert acq_deal in deal_ids
    assert str(land_deal) not in deal_ids


def test_pipeline_analytics_death_reasons_and_deal_type_breakdown(client_and_token, org_id):
    client, token = client_and_token
    _insert_deal(org_id, status="dead", property_address="Dead 1", close_reason_code="deal_failed_underwriting")
    _insert_deal(org_id, status="dead", property_address="Dead 2", close_reason_code="deal_failed_underwriting")
    _insert_deal(org_id, status="lead", property_address="Live deal")

    resp = client.get("/api/v1/pipeline/analytics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["death_reason_distribution"]["deal_failed_underwriting"] == 2
    assert body["deal_type_breakdown"]["acquisition"] == 3


def test_pipeline_analytics_average_days_per_stage(client_and_token, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    deal_id = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status) "
        "values (%s, 'Stage timing deal', 'acquisition', 'screened') returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.execute(
        "insert into deal_status_history (deal_id, org_id, status, entered_at, exited_at) "
        "values (%s, %s, 'lead', now() - interval '5 days', now() - interval '2 days')",
        (deal_id, org_id),
    )
    conn.close()

    resp = client.get("/api/v1/pipeline/analytics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["average_days_per_stage"]["lead"] == pytest.approx(3.0, abs=0.1)


def test_deal_status_update_records_history(client_and_token, org_id):
    client, token = client_and_token
    lead_deal = _insert_deal(org_id, status="lead")
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_status_history (deal_id, org_id, status) values (%s, %s, 'lead')",
        (lead_deal, org_id),
    )
    conn.close()

    resp = client.patch(
        f"/api/v1/deals/{lead_deal}/status",
        headers={"Authorization": f"Bearer {token}"}, json={"status": "screened"},
    )
    assert resp.status_code == 200, resp.text

    conn = psycopg.connect(settings.database_url, autocommit=True)
    rows = conn.execute(
        "select status, exited_at from deal_status_history where deal_id = %s order by entered_at", (lead_deal,)
    ).fetchall()
    conn.close()
    assert rows[0][0] == "lead" and rows[0][1] is not None
    assert rows[1][0] == "screened" and rows[1][1] is None


def test_deal_status_update_dead_requires_close_reason(client_and_token, org_id):
    client, token = client_and_token
    lead_deal = _insert_deal(org_id, status="lead")

    resp = client.patch(
        f"/api/v1/deals/{lead_deal}/status",
        headers={"Authorization": f"Bearer {token}"}, json={"status": "dead"},
    )
    assert resp.status_code == 422
