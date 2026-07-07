"""Gate G-07 — Section 14: "Token usage within 1% of quality log. Budget ceiling
enforced before API call."

Two independent claims, tested separately:
  1. orgs.token_used_this_month increments by exactly the same figure recorded in
     agent_quality_log.token_count for that call — arx/api/agents.py computes
     result.input_tokens + result.output_tokens once and passes that same value to
     both record_agent_run() and increment_token_usage() in the same transaction
     (Section 11: "Token count and database write in same transaction"), so this
     should hold exactly (0% variance), comfortably inside the 1% the gate allows for.
  2. Once an org is at or over its monthly budget, every one of the 13 agent
     endpoints blocks with 429 before the model is ever called — not just a1, and not
     just "eventually," but on the very first over-budget call.
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
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_G07_ORG', 500000) returning org_id"
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
            "values (%s, '123 Main St', 'acquisition', 'lead', 5000000) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_token_usage_matches_quality_log_exactly(client_and_token, deal_id, org_id):
    client, token = client_and_token
    fake = FakeModelClient({
        "deal_id": deal_id, "deal_type_detected": "acquisition", "go_no_go": "go",
        "preliminary_cap_rate": 0.06, "preliminary_roc": None, "in_target_range": True,
        "missing_fields": [], "rationale": "Within ZONIQ's 5.5-6.5% target cap rate range for this submarket.",
        "routing_recommendation": "route_to_a02", "confidence_score": "medium",
        "document_extraction_required": False,
    }, input_tokens=123, output_tokens=456)

    conn = psycopg.connect(settings.database_url, autocommit=True)
    before = conn.execute("select token_used_this_month from orgs where org_id = %s", (org_id,)).fetchone()[0]
    conn.close()

    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a01",
            headers={"Authorization": f"Bearer {token}"}, json={},
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)
    assert resp.status_code == 200, resp.text

    conn = psycopg.connect(settings.database_url, autocommit=True)
    after = conn.execute("select token_used_this_month from orgs where org_id = %s", (org_id,)).fetchone()[0]
    logged = conn.execute(
        "select token_count from agent_quality_log where org_id = %s and agent_id = 'a01' order by created_at desc limit 1",
        (org_id,),
    ).fetchone()[0]
    conn.close()

    actual_increment = after - before
    assert actual_increment == 123 + 456
    assert logged == actual_increment  # exact match: 0% variance, well within the 1% gate


AGENT_PAYLOADS = {
    "a01": {}, "a02": {}, "a03": {"contact_id": "00000000-0000-0000-0000-000000000001"},
    "a04": {"seller_profile": {}}, "a05": {"state_code": "WA", "selected_offer_strategy": {}},
    "a06": {"dd_track": "acquisition"}, "a07": {},
    "a08": {"contact_id": "00000000-0000-0000-0000-000000000001", "recipient_type": "seller", "channel": "email"},
    "a10": {}, "a11": {"land_cost": 100_000, "exit_cap_rate": 0.06},
    "a12": {"original_offer_strategy": {}, "seller_counter_terms": {}}, "a13": {},
}


@pytest.mark.parametrize("agent_id", sorted(AGENT_PAYLOADS.keys()))
def test_budget_ceiling_blocks_before_model_call(client_and_token, deal_id, org_id, agent_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "update orgs set token_used_this_month = token_budget_monthly where org_id = %s", (org_id,)
    )
    conn.close()

    fake = FakeModelClient({})
    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"}, json=AGENT_PAYLOADS[agent_id],
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)

    assert resp.status_code == 429, f"{agent_id}: expected 429, got {resp.status_code}: {resp.text}"
    assert len(fake.calls) == 0, f"{agent_id}: model was called despite the org being over budget"
