"""Integration tests for the Audit & Compliance Report (Section 57) and the
assumption-override endpoint (Section 21) against a live Postgres + FastAPI app.
Skipped automatically if no DATABASE_URL is reachable.
"""
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
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_AUDIT_ORG', 500000) returning org_id"
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
            "values (%s, '123 Main St', 'acquisition', 'underwriting', 5000000) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_audit_report_unknown_deal_404s(client_and_token):
    client, token = client_and_token
    resp = client.get(
        "/api/v1/deals/00000000-0000-0000-0000-000000000000/audit-report",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_audit_report_pdf_format_returns_501(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.get(
        f"/api/v1/deals/{deal_id}/audit-report?format=pdf", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 501


def test_create_assumption_override_persists_and_appears_in_audit_report(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/assumption-overrides",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "input_field": "vacancy_rate", "input_value": 0.10, "financial_track": "acquisition",
            "override_note": "Submarket vacancy is running higher than the org default suggests.",
        },
    )
    assert resp.status_code == 201, resp.text

    report = client.get(f"/api/v1/deals/{deal_id}/audit-report", headers={"Authorization": f"Bearer {token}"})
    assert report.status_code == 200, report.text
    overrides = report.json()["assumptions_and_overrides"]
    assert len(overrides) == 1
    assert overrides[0]["input_field"] == "vacancy_rate"
    assert overrides[0]["assumption_type"] == "user_provided"


def test_assumption_override_note_too_short_rejected(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/assumption-overrides",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "input_field": "vacancy_rate", "input_value": 0.10, "financial_track": "acquisition",
            "override_note": "too short",
        },
    )
    assert resp.status_code == 422


def test_audit_report_includes_snapshots_status_history_and_documents(client_and_token, deal_id, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, input_payload, output_payload) "
        "values (%s, %s, 'a02', 1, true, '{}'::jsonb, '{}'::jsonb)",
        (deal_id, org_id),
    )
    conn.execute(
        "insert into deal_status_history (deal_id, org_id, status) values (%s, %s, 'underwriting')",
        (deal_id, org_id),
    )
    conn.execute(
        "insert into documents (deal_id, org_id, doc_type, filename, storage_path) "
        "values (%s, %s, 'om', 'offering_memo.pdf', 's3://bucket/om.pdf')",
        (deal_id, org_id),
    )
    conn.close()

    resp = client.get(f"/api/v1/deals/{deal_id}/audit-report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["agent_outputs"]) == 1
    assert body["agent_outputs"][0]["agent_id"] == "a02"
    assert len(body["status_changes"]) == 1
    assert len(body["documents"]) == 1
    assert body["documents"][0]["filename"] == "offering_memo.pdf"
