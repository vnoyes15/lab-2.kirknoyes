"""Gate G-02 — Section 14: "Zero cross-org data leakage under any authenticated
request across all 13 agents."

test_phase1_smoke.py already proves this for plain deal reads/writes. This gate test
exercises it specifically for every one of the 13 agent invocation endpoints: org B's
token, pointed at org A's deal_id, must 404 every single time — the same
indistinguishable-from-nonexistent behavior MT4 requires everywhere else in the API —
and, critically, must never reach the model client (a leak that only shows up in
*billing*, not in the HTTP response, would otherwise go undetected). No agent's
Pydantic validation gets in the way of proving this: every payload below is a
minimally valid one for that agent, so the request reaches _get_deal's org check
rather than 422ing on unrelated missing fields first.
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
def two_orgs_and_deal():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    org_a_id = org_b_id = None
    try:
        org_a_id = str(conn.execute(
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_G02_ORG_A', 500000) returning org_id"
        ).fetchone()[0])
        org_b_id = str(conn.execute(
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_G02_ORG_B', 500000) returning org_id"
        ).fetchone()[0])
        deal_id = str(conn.execute(
            "insert into deals (org_id, property_address, deal_type, status, asking_price) "
            "values (%s, '123 Main St', 'acquisition', 'underwriting', 5000000) returning deal_id",
            (org_a_id,),
        ).fetchone()[0])
        yield org_a_id, org_b_id, deal_id
    finally:
        with conn.transaction():
            conn.execute("set local arx.allow_snapshot_delete = 'true'")
            for oid in (org_a_id, org_b_id):
                if oid:
                    conn.execute("delete from orgs where org_id = %s", (oid,))
        conn.close()


@pytest.fixture
def client():
    from arx.api.main import app
    return TestClient(app)


AGENT_PAYLOADS = {
    "a01": {},
    "a02": {},
    "a03": {"contact_id": "00000000-0000-0000-0000-000000000001"},
    "a04": {"seller_profile": {}},
    "a05": {"state_code": "WA", "selected_offer_strategy": {}},
    "a06": {"dd_track": "acquisition"},
    "a07": {},
    "a08": {"contact_id": "00000000-0000-0000-0000-000000000001", "recipient_type": "seller", "channel": "email"},
    "a10": {},
    "a11": {"land_cost": 100_000, "exit_cap_rate": 0.06},
    "a12": {"original_offer_strategy": {}, "seller_counter_terms": {}},
    "a13": {},
}


@pytest.mark.parametrize("agent_id", sorted(AGENT_PAYLOADS.keys()))
def test_agent_endpoint_404s_for_cross_org_deal(client, two_orgs_and_deal, agent_id):
    _, org_b_id, deal_id = two_orgs_and_deal
    token_b = _mint_token(org_b_id)
    fake = FakeModelClient({})

    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token_b}"}, json=AGENT_PAYLOADS[agent_id],
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)

    assert resp.status_code == 404, f"{agent_id}: expected 404, got {resp.status_code}: {resp.text}"
    assert len(fake.calls) == 0, f"{agent_id}: model was called for a cross-org deal — leak is billable, not just visible"


def test_a09_document_upload_404s_for_cross_org_deal(client, two_orgs_and_deal):
    _, org_b_id, deal_id = two_orgs_and_deal
    token_b = _mint_token(org_b_id)
    fake = FakeModelClient({})

    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/documents",
            headers={"Authorization": f"Bearer {token_b}"},
            data={"doc_type": "other"}, files={"file": ("test.txt", b"hello world", "text/plain")},
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)

    assert resp.status_code == 404
    assert len(fake.calls) == 0


def test_deal_readable_by_owning_org_not_by_other(client, two_orgs_and_deal):
    org_a_id, org_b_id, deal_id = two_orgs_and_deal
    resp_a = client.get(f"/api/v1/deals/{deal_id}", headers={"Authorization": f"Bearer {_mint_token(org_a_id)}"})
    resp_b = client.get(f"/api/v1/deals/{deal_id}", headers={"Authorization": f"Bearer {_mint_token(org_b_id)}"})
    assert resp_a.status_code == 200
    assert resp_b.status_code == 404
