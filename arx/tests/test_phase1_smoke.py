"""Phase 1 foundation smoke test — Section 86 S9.

"This test creates a test org, posts a deal via the intake API, verifies org_id
isolation, then cleans up. All assertions green = Phase 1 foundation is solid."

Requires a real DATABASE_URL with Phase 1 migrations applied (scripts/migrate.py) —
this is an integration test, not a unit test, and is skipped automatically if no
database is reachable so `pytest arx/tests/` still runs clean in an environment with
no Postgres configured (e.g. a laptop that hasn't done the Section 86 setup yet).

N4: "Label all test data clearly. Separate test schema." — this test's org names are
prefixed TEST_SMOKE_ so they're unmistakable in any environment, and it deletes every
row it creates in a finally block regardless of pass/fail.
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

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="No reachable DATABASE_URL configured (Section 86 S3/S5)")


def _mint_token(org_id: str, role: str = "analyst") -> str:
    return jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000001", "org_id": org_id, "role": role,
         "exp": int(time.time()) + 3600},
        settings.secret_key,
        algorithm="HS256",
    )


@pytest.fixture
def two_test_orgs():
    """Creates org A and org B directly (bypassing RLS, as the seed script does — this
    is bootstrap, not request-handling code) and tears both down afterward."""
    conn = psycopg.connect(settings.database_url, autocommit=True)
    org_a_id = org_b_id = None
    try:
        with conn.cursor() as cur:
            cur.execute("insert into orgs (org_name) values ('TEST_SMOKE_ORG_A') returning org_id")
            org_a_id = str(cur.fetchone()[0])
            cur.execute("insert into orgs (org_name) values ('TEST_SMOKE_ORG_B') returning org_id")
            org_b_id = str(cur.fetchone()[0])
        yield org_a_id, org_b_id
    finally:
        with conn.cursor() as cur:
            for org_id in (org_a_id, org_b_id):
                if org_id:
                    cur.execute("delete from orgs where org_id = %s", (org_id,))  # cascades to deals
        conn.close()


@pytest.fixture
def client():
    from arx.api.main import app
    return TestClient(app)


def test_phase1_foundation(client, two_test_orgs):
    org_a_id, org_b_id = two_test_orgs
    token_a = _mint_token(org_a_id)
    token_b = _mint_token(org_b_id)

    # 1. Post a deal via the intake API as org A.
    resp = client.post(
        "/api/v1/deals/intake",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "property_address": "1 Smoke Test Ave",
            "source": "phase1_smoke_test",
            "org_id": org_a_id,
            "deal_type": "acquisition",
        },
    )
    assert resp.status_code == 201, resp.text
    deal_id = resp.json()["deal_id"]
    assert resp.json()["created"] is True

    # 2. Re-posting the same address dedups onto the same deal_id (Section 19).
    resp_dedup = client.post(
        "/api/v1/deals/intake",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "property_address": "1 Smoke Test Ave",
            "source": "phase1_smoke_test_dup",
            "org_id": org_a_id,
            "deal_type": "acquisition",
        },
    )
    assert resp_dedup.status_code == 201
    assert resp_dedup.json() == {"deal_id": deal_id, "created": False}

    # 3. Org A can read its own deal.
    resp_get_own = client.get(f"/api/v1/deals/{deal_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert resp_get_own.status_code == 200
    assert resp_get_own.json()["deal_id"] == deal_id

    # 4. Org B isolation (G-02): the same deal_id is invisible under org B's token —
    # verifies RLS end-to-end through the live API, not just at the SQL layer.
    resp_get_other = client.get(f"/api/v1/deals/{deal_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_get_other.status_code == 404

    # 5. Org B cannot spoof org_id in the request body to write into org A.
    resp_spoof = client.post(
        "/api/v1/deals/intake",
        headers={"Authorization": f"Bearer {token_b}"},
        json={
            "property_address": "2 Spoofed Ave",
            "source": "phase1_smoke_test",
            "org_id": org_a_id,  # org B's token, but claiming org A in the body
            "deal_type": "acquisition",
        },
    )
    assert resp_spoof.status_code == 403
