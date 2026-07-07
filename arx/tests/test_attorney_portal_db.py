"""Integration tests for the Attorney Portal (Section 71) against a live Postgres +
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
        _org_id = str(conn.execute(
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_ATTORNEY_ORG', 500000) returning org_id"
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


@pytest.fixture
def attorney_user_id(org_id, deal_id):
    attorney_id = str(uuid.uuid4())
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into deal_attorney_access (deal_id, org_id, attorney_user_id) values (%s, %s, %s)",
        (deal_id, org_id, attorney_id),
    )
    conn.close()
    return attorney_id


@pytest.fixture
def client(org_id):
    from arx.api.main import app
    return TestClient(app)


def test_attorney_without_access_gets_404(client, org_id, deal_id):
    token = _mint_token(org_id, str(uuid.uuid4()), "attorney")
    resp = client.get(f"/api/v1/attorney/deals/{deal_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


def test_attorney_with_access_sees_curated_deal_view(client, org_id, deal_id, attorney_user_id):
    token = _mint_token(org_id, attorney_user_id, "attorney")
    resp = client.get(f"/api/v1/attorney/deals/{deal_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deal_id"] == deal_id
    # Financial details/seller profile/outreach history must never appear.
    assert "asking_price" not in body
    assert "seller_archetype" not in body
    assert "outreach" not in body


def test_attorney_list_deals_only_shows_granted_deals(client, org_id, deal_id, attorney_user_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    other_deal = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price) "
        "values (%s, 'Other Deal', 'acquisition', 'lead', 1000000) returning deal_id",
        (org_id,),
    ).fetchone()[0]
    conn.close()

    token = _mint_token(org_id, attorney_user_id, "attorney")
    resp = client.get("/api/v1/attorney/deals", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    deal_ids = [d["deal_id"] for d in resp.json()]
    assert deal_id in deal_ids
    assert str(other_deal) not in deal_ids


def test_attorney_can_flag_issue_as_comment(client, org_id, deal_id, attorney_user_id):
    token = _mint_token(org_id, attorney_user_id, "attorney")
    resp = client.post(
        f"/api/v1/attorney/deals/{deal_id}/comments",
        headers={"Authorization": f"Bearer {token}"},
        json={"body": "Title report shows an unresolved lien from 2019."},
    )
    assert resp.status_code == 201, resp.text

    admin_token = _mint_token(org_id, str(uuid.uuid4()), "admin")
    list_resp = client.get(f"/api/v1/deals/{deal_id}/comments", headers={"Authorization": f"Bearer {admin_token}"})
    assert list_resp.status_code == 200, list_resp.text
    comments = list_resp.json()
    assert len(comments) == 1
    assert comments[0]["author_role"] == "attorney"
    assert "lien" in comments[0]["body"]


def test_attorney_cannot_comment_without_access(client, org_id, deal_id):
    token = _mint_token(org_id, str(uuid.uuid4()), "attorney")
    resp = client.post(
        f"/api/v1/attorney/deals/{deal_id}/comments",
        headers={"Authorization": f"Bearer {token}"}, json={"body": "Should not work."},
    )
    assert resp.status_code == 404


def test_attorney_can_confirm_legal_review_task(client, org_id, deal_id, attorney_user_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    task_id = conn.execute(
        "insert into deal_tasks (deal_id, org_id, title, status, priority, source_agent) "
        "values (%s, %s, 'DD: legal_and_title_review', 'in_progress', 'high', 'a06') returning task_id",
        (deal_id, org_id),
    ).fetchone()[0]
    conn.close()

    token = _mint_token(org_id, attorney_user_id, "attorney")
    resp = client.patch(
        f"/api/v1/attorney/deals/{deal_id}/tasks/{task_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "complete"

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute("select status, completed_at from deal_tasks where task_id = %s", (task_id,)).fetchone()
    conn.close()
    assert row[0] == "complete"
    assert row[1] is not None


def test_attorney_cannot_confirm_non_legal_review_task(client, org_id, deal_id, attorney_user_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    task_id = conn.execute(
        "insert into deal_tasks (deal_id, org_id, title, status, priority, source_agent) "
        "values (%s, %s, 'DD: physical_inspection', 'in_progress', 'medium', 'a06') returning task_id",
        (deal_id, org_id),
    ).fetchone()[0]
    conn.close()

    token = _mint_token(org_id, attorney_user_id, "attorney")
    resp = client.patch(
        f"/api/v1/attorney/deals/{deal_id}/tasks/{task_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute("select status from deal_tasks where task_id = %s", (task_id,)).fetchone()
    conn.close()
    assert row[0] == "in_progress"  # unchanged


def test_admin_can_grant_attorney_access(client, org_id, deal_id):
    admin_token = _mint_token(org_id, str(uuid.uuid4()), "admin")
    new_attorney_id = str(uuid.uuid4())
    resp = client.post(
        f"/api/v1/deals/{deal_id}/attorney-access",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"attorney_user_id": new_attorney_id},
    )
    assert resp.status_code == 201, resp.text

    attorney_token = _mint_token(org_id, new_attorney_id, "attorney")
    resp = client.get(f"/api/v1/attorney/deals/{deal_id}", headers={"Authorization": f"Bearer {attorney_token}"})
    assert resp.status_code == 200, resp.text


def test_non_admin_cannot_grant_attorney_access(client, org_id, deal_id):
    analyst_token = _mint_token(org_id, str(uuid.uuid4()), "analyst")
    resp = client.post(
        f"/api/v1/deals/{deal_id}/attorney-access",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"attorney_user_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 403
