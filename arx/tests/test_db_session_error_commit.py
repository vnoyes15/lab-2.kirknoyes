"""Regression test for a bug found while building the Phase 4 notification framework:
db_session() wrapped an entire request in one outer `with conn.transaction():`, so any
endpoint that wrote to error_log (or notifications) and then raised HTTPException to
return a structured error response had that write silently rolled back — the
HTTPException propagating out through db_session's own transaction context triggered a
ROLLBACK of everything, discarding the error_log row even though the response body's
error_id looked like a real, persisted UUID. Section 10 EH4 ("All unrecoverable errors
write to error_log") was violated for every agent's error path across every phase
until arx/db/connection.py's fix (HTTPException raised inside the request is now
special-cased to let the transaction commit before re-raising).
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


def test_agent_validation_failure_persists_error_log_row_despite_http_exception():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    org_id = str(conn.execute(
        "insert into orgs (org_name, token_budget_monthly) values ('TEST_DB_SESSION_ORG', 500000) returning org_id"
    ).fetchone()[0])
    conn.execute(
        "insert into org_jurisdictions (org_id, state_code, rent_control_active, rent_control_cap_formula, "
        "attorney_review_required) values (%s, 'WA', true, '7%% + CPI, or 10%%, whichever is lower', true)",
        (org_id,),
    )
    deal_id = str(conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price) "
        "values (%s, '123 Main St', 'acquisition', 'lead', 1000000) returning deal_id",
        (org_id,),
    ).fetchone()[0])
    conn.close()

    try:
        from arx.api.main import app
        client = TestClient(app)
        token = _mint_token(org_id)

        # escrow_reference_present=False fails A05Output's model_validator (WA1) —
        # this is the exact "record_error then raise 422" path that was silently
        # discarding its own error_log write before the fix.
        fake = FakeModelClient({
            "loi_text": "x" * 520,
            "attorney_review_warning": "Buyer's attorney must review this LOI before execution.",
            "escrow_reference_present": False,
            "jurisdiction_flags": ["wa_rent_control_rcw59_18"],
        })
        app.dependency_overrides[model_client_dependency] = lambda: fake
        try:
            resp = client.post(
                f"/api/v1/deals/{deal_id}/agents/a05",
                headers={"Authorization": f"Bearer {token}"},
                json={"state_code": "WA", "selected_offer_strategy": {"purchase_price": 4_900_000}},
            )
        finally:
            app.dependency_overrides.pop(model_client_dependency, None)

        assert resp.status_code == 422
        error_id = resp.json()["detail"]["error_id"]
        assert error_id

        conn = psycopg.connect(settings.database_url, autocommit=True)
        row = conn.execute(
            "select error_id from error_log where org_id = %s and error_id = %s", (org_id, error_id)
        ).fetchone()
        conn.close()
        assert row is not None, (
            "error_log row was not persisted — the HTTPException raised after "
            "record_error() rolled back the write (the exact bug this test guards)."
        )
    finally:
        conn = psycopg.connect(settings.database_url, autocommit=True)
        with conn.transaction():
            conn.execute("set local arx.allow_snapshot_delete = 'true'")
            conn.execute("delete from orgs where org_id = %s", (org_id,))
        conn.close()
