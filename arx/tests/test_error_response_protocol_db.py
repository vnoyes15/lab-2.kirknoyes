"""Integration tests for Section 78 Error Response Protocol completion against a live
Postgres + FastAPI app:
  EP1 - "Admin notified immediately for errors on deals in active stages."
  EP2 - resolution_status/resolution_notes tracked through to closure (GET/PATCH
        /api/v1/errors).
  EP3 - error record visible in the audit report.
Skipped automatically if no DATABASE_URL is reachable.
"""
import time

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

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
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_ERR_PROTO_ORG', 500000) returning org_id"
        ).fetchone()[0])
        yield _org_id
    finally:
        if _org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (_org_id,))
        conn.close()


def _insert_deal(org_id: str, status: str = "lead") -> str:
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        row = conn.execute(
            "insert into deals (org_id, property_address, deal_type, status, asking_price) "
            "values (%s, '123 Main St', 'acquisition', %s, 5000000) returning deal_id",
            (org_id, status),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def _admin_token(org_id: str) -> str:
    return _mint_token(org_id, role="admin")


def _trigger_a01_failure(client, token, deal_id):
    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: FakeModelClient({})
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a01",
            headers={"Authorization": f"Bearer {token}"}, json={},
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)
    assert resp.status_code == 422, resp.text
    return resp.json()["detail"]["error_id"]


def test_error_on_active_deal_notifies(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, status="underwriting")
    _trigger_a01_failure(client, token, deal_id)

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'error_on_active_deal'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 1


def test_error_on_closed_deal_does_not_notify(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, status="closed")
    _trigger_a01_failure(client, token, deal_id)

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'error_on_active_deal'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 0


def test_admin_can_list_and_resolve_error(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, status="underwriting")
    error_id = _trigger_a01_failure(client, token, deal_id)

    admin_token = _admin_token(org_id)
    list_resp = client.get("/api/v1/errors", headers={"Authorization": f"Bearer {admin_token}"})
    assert list_resp.status_code == 200, list_resp.text
    ids = [e["error_id"] for e in list_resp.json()]
    assert error_id in ids

    open_resp = client.get(
        "/api/v1/errors?resolution_status=open", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert error_id in [e["error_id"] for e in open_resp.json()]

    patch_resp = client.patch(
        f"/api/v1/errors/{error_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"resolution_status": "resolved", "resolution_notes": "Fixed the upstream data feed."},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["resolution_status"] == "resolved"

    resolved_resp = client.get(
        "/api/v1/errors?resolution_status=resolved", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert error_id in [e["error_id"] for e in resolved_resp.json()]


def test_analyst_cannot_access_errors_endpoint(client_and_token):
    client, token = client_and_token
    resp = client.get("/api/v1/errors", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_resolve_unknown_error_404s(org_id):
    from arx.api.main import app
    client = TestClient(app)
    admin_token = _admin_token(org_id)
    resp = client.patch(
        "/api/v1/errors/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"resolution_status": "investigating"},
    )
    assert resp.status_code == 404


def test_error_visible_in_audit_report(client_and_token, org_id):
    client, token = client_and_token
    deal_id = _insert_deal(org_id, status="underwriting")
    error_id = _trigger_a01_failure(client, token, deal_id)

    resp = client.get(f"/api/v1/deals/{deal_id}/audit-report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    errors = resp.json()["errors"]
    assert len(errors) == 1
    assert errors[0]["error_id"] == error_id
    assert errors[0]["resolution_status"] == "open"
