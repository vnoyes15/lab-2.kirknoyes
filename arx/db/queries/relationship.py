"""Relationship warmth persistence — Section 38.

Recalculates contacts.warmth_score from last_contacted_at using the deterministic
logic in arx/agents/relationship_warmth.py. Section 38 describes this as a nightly
Celery Beat job (N8) once outreach_log exists (Phase 4) — this function is what that
job will call; for now it's invoked directly (e.g. after A-08 exists, or manually via
an admin action) since there's no scheduler wired yet in Phase 3.
"""
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from arx.agents.relationship_warmth import compute_warmth


def recalculate_org_warmth(conn: psycopg.Connection, org_id: str, now: datetime | None = None) -> int:
    """Recomputes and persists warmth_score for every contact in an org. Returns the
    number of contacts updated."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select contact_id, last_contacted_at from contacts where org_id = %s", (org_id,))
        contacts = cur.fetchall()

    for contact in contacts:
        warmth = compute_warmth(contact["last_contacted_at"], now=now)
        conn.execute(
            "update contacts set warmth_score = %s where contact_id = %s",
            (warmth, contact["contact_id"]),
        )

    return len(contacts)
