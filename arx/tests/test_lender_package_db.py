"""Integration tests for Lender Package Generation (Section 71) against a live
Postgres + FastAPI app. Skipped automatically if no DATABASE_URL is reachable.
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
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_LENDER_PKG_ORG', 500000) returning org_id"
        ).fetchone()[0])
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
            "values (%s, '123 Main St', 'acquisition', 'due_diligence', 5000000) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


def _insert_snapshot(org_id, deal_id, agent_id, payload, is_active=True):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    next_version = conn.execute(
        "select coalesce(max(version_number), 0) + 1 from deal_snapshots where deal_id = %s and agent_id = %s",
        (deal_id, agent_id),
    ).fetchone()[0]
    conn.execute(
        "insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active, "
        "input_payload, output_payload) values (%s, %s, %s, %s, %s, '{}'::jsonb, %s::jsonb)",
        (deal_id, org_id, agent_id, next_version, is_active, json.dumps(payload)),
    )
    conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_lender_package_unknown_deal_404s(client_and_token):
    client, token = client_and_token
    resp = client.get(
        "/api/v1/deals/00000000-0000-0000-0000-000000000000/lender-package",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_lender_package_assembles_available_sections(client_and_token, deal_id, org_id):
    client, token = client_and_token
    _insert_snapshot(org_id, deal_id, "a07", {
        "audience_version": "internal", "sections": {"executive_summary": "Great deal."},
    })
    _insert_snapshot(org_id, deal_id, "a02", {
        "purchase_price": 5_000_000, "loan_amount": 3_750_000, "ltv": 0.75, "interest_rate": 0.065,
        "noi": 300_000,
    })
    _insert_snapshot(org_id, deal_id, "a09", {
        "document_type_detected": "rent_roll", "extraction_completeness": "complete",
        "extracted_fields": {"total_units": {"value": 24, "confidence": "high"}},
        "missing_required_fields": [],
    }, is_active=False)
    _insert_snapshot(org_id, deal_id, "a09", {
        "document_type_detected": "title_commitment", "extraction_completeness": "partial",
        "extracted_fields": {"exceptions": {"value": ["easement"], "confidence": "medium"}},
        "missing_required_fields": ["legal_description"],
    }, is_active=False)

    resp = client.get(f"/api/v1/deals/{deal_id}/lender-package", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["deal_memo"]["sections"]["executive_summary"] == "Great deal."
    assert body["underwriting_output"]["agent_id"] == "a02"
    assert body["underwriting_output"]["output"]["purchase_price"] == 5_000_000
    assert body["rent_roll_summary"]["extracted_fields"]["total_units"] == 24
    assert body["title_commitment_summary"]["extraction_completeness"] == "partial"
    assert body["property_inspection_summary"] is None  # nothing extracted for this deal
    assert body["operating_track_record"] is None
    assert "No fund-level historical track-record" in body["operating_track_record_note"]
    assert body["capital_stack"]["senior_debt"] == 3_750_000
    assert body["capital_stack"]["equity"] == pytest.approx(1_250_000)


def test_lender_package_development_deal_uses_a11(client_and_token, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    dev_deal_id = str(conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price) "
        "values (%s, 'Dev Site', 'development', 'construction', 2000000) returning deal_id",
        (org_id,),
    ).fetchone()[0])
    conn.close()
    _insert_snapshot(org_id, dev_deal_id, "a11", {"total_project_cost": 10_000_000})

    resp = client.get(f"/api/v1/deals/{dev_deal_id}/lender-package", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["underwriting_output"]["agent_id"] == "a11"
    assert body["underwriting_output"]["output"]["total_project_cost"] == 10_000_000
    assert body["capital_stack"]["total_project_cost"] == 10_000_000


def test_lender_package_includes_latest_equity_waterfall(client_and_token, deal_id, org_id):
    client, token = client_and_token
    _insert_snapshot(org_id, deal_id, "a02", {
        "purchase_price": 5_000_000, "loan_amount": 3_750_000, "ltv": 0.75, "interest_rate": 0.065,
        "noi": 300_000,
    })
    client.post(
        f"/api/v1/deals/{deal_id}/waterfall",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "structure_type": "simple_lp_gp", "lp_capital": 1_000_000, "gp_capital": 250_000,
            "total_distributable_proceeds": 2_000_000, "hurdle_moic": 1.5,
            "base_split_lp_pct": 0.8, "base_split_gp_pct": 0.2,
            "promote_split_lp_pct": 0.7, "promote_split_gp_pct": 0.3,
        },
    )

    resp = client.get(f"/api/v1/deals/{deal_id}/lender-package", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    equity_structure = resp.json()["capital_stack"]["equity_structure"]
    assert equity_structure["structure_type"] == "simple_lp_gp"
    assert equity_structure["lp_capital"] == 1_000_000
