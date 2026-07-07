"""Integration tests for Section 73 Deal Team Task Management against a live Postgres +
FastAPI app: the manual task-creation endpoint (with its task_assigned notification) and
the due_diligence -> closed enforcement in PATCH /deals/{id}/status ("A deal cannot
advance ... to closed while any task with priority = high has status = not_started or
in_progress"). Skipped automatically if no DATABASE_URL is reachable.
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
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_TASKMGMT_ORG', 500000) returning org_id"
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
            "values (%s, '123 Main St, Tacoma WA', 'acquisition', 'due_diligence', 5000000) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_create_task_persists_and_notifies_assignee(client_and_token, deal_id, org_id):
    client, token = client_and_token
    assignee = "00000000-0000-0000-0000-0000000000bb"
    resp = client.post(
        f"/api/v1/deals/{deal_id}/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "Order updated title report",
            "description": "Prior report is 90+ days old.",
            "assigned_to_user_id": assignee,
            "priority": "high",
        },
    )
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["task_id"]

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select title, priority, status, assigned_to_user_id, source_agent from deal_tasks where task_id = %s",
        (task_id,),
    ).fetchone()
    notif_count = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'task_assigned' "
        "and recipient_user_id = %s",
        (org_id, assignee),
    ).fetchone()[0]
    conn.close()

    assert row[:3] == ("Order updated title report", "high", "not_started")
    assert str(row[3]) == assignee
    assert row[4] is None
    assert notif_count == 1


def test_create_task_without_assignee_sends_no_notification(client_and_token, deal_id, org_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Follow up with broker"},
    )
    assert resp.status_code == 201, resp.text

    conn = psycopg.connect(settings.database_url, autocommit=True)
    notif_count = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'task_assigned'", (org_id,)
    ).fetchone()[0]
    conn.close()
    assert notif_count == 0


def test_create_task_unknown_deal_404s(client_and_token):
    client, token = client_and_token
    resp = client.post(
        "/api/v1/deals/00000000-0000-0000-0000-000000000000/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Whatever"},
    )
    assert resp.status_code == 404


def test_list_tasks_returns_created_tasks(client_and_token, deal_id):
    client, token = client_and_token
    client.post(
        f"/api/v1/deals/{deal_id}/tasks",
        headers={"Authorization": f"Bearer {token}"}, json={"title": "Task A"},
    )
    client.post(
        f"/api/v1/deals/{deal_id}/tasks",
        headers={"Authorization": f"Bearer {token}"}, json={"title": "Task B"},
    )
    resp = client.get(f"/api/v1/deals/{deal_id}/tasks", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    titles = {t["title"] for t in resp.json()}
    assert titles == {"Task A", "Task B"}


def test_close_blocked_while_high_priority_task_open(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Resolve title lien", "priority": "high"},
    )
    assert resp.status_code == 201, resp.text

    close_resp = client.patch(
        f"/api/v1/deals/{deal_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "closed"},
    )
    assert close_resp.status_code == 409, close_resp.text
    detail = close_resp.json()["detail"]
    assert "high-priority tasks" in detail["message"]
    assert len(detail["blocking_tasks"]) == 1


def test_close_succeeds_once_high_priority_task_resolved(client_and_token, deal_id, org_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Resolve title lien", "priority": "high"},
    )
    task_id = resp.json()["task_id"]

    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "update deal_tasks set status = 'complete', completed_at = now() where task_id = %s", (task_id,)
    )
    conn.close()

    close_resp = client.patch(
        f"/api/v1/deals/{deal_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "closed"},
    )
    assert close_resp.status_code == 200, close_resp.text


def test_close_ignores_low_and_medium_priority_open_tasks(client_and_token, deal_id):
    client, token = client_and_token
    for priority in ("low", "medium"):
        resp = client.post(
            f"/api/v1/deals/{deal_id}/tasks",
            headers={"Authorization": f"Bearer {token}"}, json={"title": f"{priority} task", "priority": priority},
        )
        assert resp.status_code == 201, resp.text

    close_resp = client.patch(
        f"/api/v1/deals/{deal_id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "closed"},
    )
    assert close_resp.status_code == 200, close_resp.text
