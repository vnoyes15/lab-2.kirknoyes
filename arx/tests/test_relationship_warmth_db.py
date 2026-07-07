"""Integration test for arx/db/queries/relationship.py against a live Postgres
instance. Skipped automatically if no DATABASE_URL is reachable.
"""
import json
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from arx.api.config import get_settings
from arx.db.queries.relationship import recalculate_org_warmth

try:
    settings = get_settings()
    _conn = psycopg.connect(settings.database_url, connect_timeout=3)
    _conn.close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="No reachable DATABASE_URL configured")

NOW = datetime(2026, 7, 7, tzinfo=timezone.utc)


@pytest.fixture
def org_with_contacts():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    org_id = None
    try:
        with conn.cursor() as cur:
            cur.execute("insert into orgs (org_name) values ('TEST_WARMTH_ORG') returning org_id")
            org_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into contacts (org_id, name, contact_category, last_contacted_at) values "
                "(%s, 'Hot Broker', 'broker', %s), (%s, 'Cold Broker', 'broker', %s), (%s, 'Never Contacted', 'broker', null)",
                (org_id, NOW - timedelta(days=5), org_id, NOW - timedelta(days=200), org_id),
            )
        yield org_id
    finally:
        if org_id:
            conn.execute("delete from orgs where org_id = %s", (org_id,))
        conn.close()


def test_recalculate_org_warmth_updates_all_contacts(org_with_contacts):
    conn = psycopg.connect(
        settings.app_database_url, autocommit=True,
    )
    conn.execute(
        "select set_config('request.jwt.claims', %s, false)",
        (json.dumps({"org_id": org_with_contacts, "role": "analyst", "sub": "00000000-0000-0000-0000-000000000001"}),),
    )
    try:
        updated_count = recalculate_org_warmth(conn, org_with_contacts, now=NOW)
        assert updated_count == 3

        rows = conn.execute(
            "select name, warmth_score from contacts where org_id = %s order by name", (org_with_contacts,)
        ).fetchall()
        warmth_by_name = dict(rows)
        assert warmth_by_name["Hot Broker"] == "hot"
        assert warmth_by_name["Cold Broker"] == "cold"
        assert warmth_by_name["Never Contacted"] == "cold"
    finally:
        conn.close()
