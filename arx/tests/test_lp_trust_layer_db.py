"""Integration tests for the LP Trust Layer (Section 49) against a live Postgres +
FastAPI app. Skipped automatically if no DATABASE_URL is reachable.
"""
import time
import uuid

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


def _mint_token(org_id: str, user_id: str, role: str) -> str:
    return jwt.encode(
        {"sub": user_id, "org_id": org_id, "role": role, "exp": int(time.time()) + 3600},
        settings.secret_key, algorithm="HS256",
    )


@pytest.fixture
def org_id():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    _org_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_LP_ORG', 500000) returning org_id"
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
def deal_id(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        row = conn.execute(
            "insert into deals (org_id, property_address, deal_type, status, asking_price) "
            "values (%s, '123 Main St', 'acquisition', 'stabilized', 1000000) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def lp_user_id(org_id, deal_id):
    lp_id = str(uuid.uuid4())
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_lp_access (deal_id, org_id, lp_user_id) values (%s, %s, %s)",
        (deal_id, org_id, lp_id),
    )
    conn.close()
    return lp_id


@pytest.fixture
def client(org_id):
    from arx.api.main import app
    return TestClient(app)


def test_lp_without_access_gets_404(client, org_id, deal_id):
    token = _mint_token(org_id, str(uuid.uuid4()), "lp")
    resp = client.get(f"/api/v1/lp/deals/{deal_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


def test_lp_with_access_sees_deal_view(client, org_id, deal_id, lp_user_id):
    token = _mint_token(org_id, lp_user_id, "lp")
    resp = client.get(f"/api/v1/lp/deals/{deal_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deal_id"] == deal_id
    assert body["status"] == "stabilized"
    # LP-hidden fields must never appear even by accident of a naive select *.
    assert "seller_archetype" not in body
    assert "offer_strategy" not in body


def test_lp_deal_view_no_investor_memo_without_active_investor_facing_a07(client, org_id, deal_id, lp_user_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, input_payload, output_payload) "
        "values (%s, %s, 'a07', 1, true, '{}'::jsonb, %s)",
        (deal_id, org_id, '{"audience_version": "internal", "sections": {"executive_summary": "internal only"}}'),
    )
    conn.close()

    token = _mint_token(org_id, lp_user_id, "lp")
    resp = client.get(f"/api/v1/lp/deals/{deal_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["investor_facing_deal_memo"] is None


def test_lp_deal_view_shows_investor_facing_memo(client, org_id, deal_id, lp_user_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, input_payload, output_payload) "
        "values (%s, %s, 'a07', 1, true, '{}'::jsonb, %s)",
        (deal_id, org_id, '{"audience_version": "investor_facing", "sections": {"executive_summary": "for investors"}}'),
    )
    conn.close()

    token = _mint_token(org_id, lp_user_id, "lp")
    resp = client.get(f"/api/v1/lp/deals/{deal_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    memo = resp.json()["investor_facing_deal_memo"]
    assert memo is not None
    assert memo["sections"]["executive_summary"] == "for investors"


def test_lp_accessible_deals_lists_only_granted_deals(client, org_id, deal_id, lp_user_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    other_deal = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status) "
        "values (%s, 'No access deal', 'acquisition', 'lead') returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.close()

    token = _mint_token(org_id, lp_user_id, "lp")
    resp = client.get("/api/v1/lp/deals", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    deal_ids = [d["deal_id"] for d in resp.json()]
    assert deal_id in deal_ids
    assert str(other_deal) not in deal_ids


def test_lp_quarterly_report_acquisition_format(client, org_id, deal_id, lp_user_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_performance (deal_id, org_id, period, actual_noi) values (%s, %s, '2026-02-01', 8000)",
        (deal_id, org_id),
    )
    conn.close()

    token = _mint_token(org_id, lp_user_id, "lp")
    resp = client.get(
        f"/api/v1/lp/report/{deal_id}", params={"period": "Q1-2026"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["format"] == "acquisition"
    assert len(body["period_performance"]) == 1


def test_lp_quarterly_report_invalid_period_422s(client, org_id, deal_id, lp_user_id):
    token = _mint_token(org_id, lp_user_id, "lp")
    resp = client.get(
        f"/api/v1/lp/report/{deal_id}", params={"period": "garbage"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 422


def test_admin_cannot_use_lp_endpoints(client, org_id, deal_id):
    token = _mint_token(org_id, str(uuid.uuid4()), "admin")
    resp = client.get(f"/api/v1/lp/deals/{deal_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_milestone_update_computes_variance_and_notifies_lp(client, org_id, lp_user_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    dev_deal = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status) "
        "values (%s, 'Dev deal', 'development', 'construction') returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.execute(
        "insert into deal_lp_access (deal_id, org_id, lp_user_id) values (%s, %s, %s)",
        (dev_deal, org_id, lp_user_id),
    )
    conn.execute(
        "insert into development_milestones (deal_id, org_id, milestone_type, projected_date, status) "
        "values (%s, %s, 'construction_complete', '2026-06-01', 'projected')",
        (dev_deal, org_id),
    )
    conn.close()

    admin_token = _mint_token(org_id, str(uuid.uuid4()), "admin")
    resp = client.patch(
        f"/api/v1/deals/{dev_deal}/milestones/construction_complete",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"actual_date": "2026-06-20", "status": "complete"},  # 19 days late
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["variance_days"] == 19

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'milestone_delay' "
        "and recipient_user_id = %s",
        (org_id, lp_user_id),
    ).fetchone()
    conn.close()
    assert row[0] == 1
