"""Integration tests for the notification framework skeleton against a live Postgres +
FastAPI app: DB persistence (arx/db/queries/notifications.py), the /api/v1/notifications
API, and the two wired trigger points (A-06 deal_advancement_blocked, A-08 daily send
limit) plus momentum_scorer's stalled-transition notification. Skipped automatically if
no DATABASE_URL is reachable.
"""
import time

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from arx.agents.a06_due_diligence import ACQUISITION_CATEGORIES
from arx.agents.model_client import model_client_dependency
from arx.api.config import get_settings
from arx.db.queries.pipeline import recalculate_org_momentum
from arx.notifications.channels import EmailChannel, InAppChannel, SMSChannel
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
        with conn.cursor() as cur:
            cur.execute(
                "insert into orgs (org_name, token_budget_monthly) values ('TEST_NOTIF_ORG', 500000) returning org_id"
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


def _override_model(fake):
    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    return app


def _clear_override():
    from arx.api.main import app
    app.dependency_overrides.pop(model_client_dependency, None)


def test_email_and_sms_channels_are_explicitly_unimplemented():
    with pytest.raises(NotImplementedError):
        EmailChannel().send(None)
    with pytest.raises(NotImplementedError):
        SMSChannel().send(None)


def test_in_app_channel_persists_and_api_lists_it(client_and_token, deal_id, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    from arx.agents.notification_rules import NotificationSpec
    spec = NotificationSpec(
        notification_type="deal_advancement_blocked", severity="warning",
        title="Test notification", body="Test body", source_agent="a06",
    )
    notification_id = InAppChannel().send(conn, org_id=org_id, spec=spec, deal_id=deal_id)
    conn.close()

    resp = client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    ids = [n["notification_id"] for n in resp.json()]
    assert notification_id in ids

    read_resp = client.post(
        f"/api/v1/notifications/{notification_id}/read", headers={"Authorization": f"Bearer {token}"}
    )
    assert read_resp.status_code == 200, read_resp.text

    unread_resp = client.get(
        "/api/v1/notifications?unread_only=true", headers={"Authorization": f"Bearer {token}"}
    )
    assert notification_id not in [n["notification_id"] for n in unread_resp.json()]


def test_read_unknown_notification_404s(client_and_token):
    client, token = client_and_token
    resp = client.post(
        "/api/v1/notifications/00000000-0000-0000-0000-000000000000/read",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def _item(category, status="complete", flag_note=None):
    return {
        "item_id": category, "category": category, "description": f"{category} review",
        "why_it_matters": "Standard due diligence for this deal.",
        "responsible_party": "buyer's attorney", "status": status,
        "flag_note": flag_note, "assigned_user_id": None,
    }


def test_a06_flagged_item_creates_deal_advancement_blocked_notification(client_and_token, deal_id, org_id):
    client, token = client_and_token
    items = [_item(c) for c in ACQUISITION_CATEGORIES]
    items[0] = _item(ACQUISITION_CATEGORIES[0], status="flagged", flag_note="Title report shows an unresolved lien from 2019.")
    fake = FakeModelClient({"dd_track": "acquisition", "checklist_items": items, "wa_rent_compliance_item": None})
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a06",
            headers={"Authorization": f"Bearer {token}"},
            json={"dd_track": "acquisition"},
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'deal_advancement_blocked'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 1


def test_a06_all_complete_creates_no_notification(client_and_token, deal_id, org_id):
    client, token = client_and_token
    fake = FakeModelClient({
        "dd_track": "acquisition",
        "checklist_items": [_item(c) for c in ACQUISITION_CATEGORIES],
        "wa_rent_compliance_item": None,
    })
    _override_model(fake)
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a06",
            headers={"Authorization": f"Bearer {token}"},
            json={"dd_track": "acquisition"},
        )
    finally:
        _clear_override()
    assert resp.status_code == 200, resp.text

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'deal_advancement_blocked'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 0


def test_a08_daily_limit_reached_creates_one_notification_not_duplicated(client_and_token, deal_id, org_id):
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    contact_id = conn.execute(
        "insert into contacts (org_id, name, contact_category) values (%s, 'Target', 'broker') returning contact_id",
        (org_id,),
    ).fetchone()[0]
    other_contact = conn.execute(
        "insert into contacts (org_id, name, contact_category) values (%s, 'Bulk Target', 'broker') returning contact_id",
        (org_id,),
    ).fetchone()[0]
    with conn.transaction():
        for _ in range(50):
            conn.execute(
                "insert into outreach_log (org_id, contact_id, recipient_type, channel, message_text) "
                "values (%s, %s, 'broker', 'email', %s)",
                (org_id, other_contact, "x" * 150),
            )
    conn.close()

    fake = FakeModelClient({
        "message_text": "Hi, I'm reaching out about a potential acquisition in your area. " * 2,
        "channel": "email", "can_spam_placeholder": "[SENDER PHYSICAL ADDRESS]",
    })
    _override_model(fake)
    try:
        for _ in range(2):
            resp = client.post(
                f"/api/v1/deals/{deal_id}/agents/a08",
                headers={"Authorization": f"Bearer {token}"},
                json={"contact_id": str(contact_id), "recipient_type": "seller", "channel": "email"},
            )
            assert resp.status_code == 429
    finally:
        _clear_override()

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from notifications where org_id = %s and notification_type = 'daily_send_limit_reached'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert row[0] == 1  # not one per rejected call


def test_momentum_scorer_creates_stalled_notification_on_transition(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    deal_id = conn.execute(
        "insert into deals (org_id, property_address, deal_type, status, asking_price, momentum_score) "
        "values (%s, 'Stalled Deal', 'acquisition', 'loi', 1000000, 80) returning deal_id",
        (org_id,),
    ).fetchone()[0]
    # Backdate status_changed_at so the status-duration penalty alone drives momentum
    # below the stalled threshold even with no activity signals to consider.
    conn.execute(
        "update deals set status_changed_at = now() - interval '100 days' where deal_id = %s", (deal_id,)
    )
    try:
        recalculate_org_momentum(conn, org_id, notify=InAppChannel())
        row = conn.execute(
            "select count(*) from notifications where org_id = %s and notification_type = 'momentum_stalled'",
            (org_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 1
