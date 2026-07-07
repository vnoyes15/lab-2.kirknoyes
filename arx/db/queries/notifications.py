"""notifications persistence — Section 06. Pairs with the pure trigger logic in
arx/agents/notification_rules.py the same way quality_log.py pairs with the
validation suites: rules decide *whether* to notify, this module only writes/reads.
"""
import psycopg
from psycopg.rows import dict_row

from arx.agents.notification_rules import NotificationSpec


def create_notification(
    conn: psycopg.Connection,
    *,
    org_id: str,
    spec: NotificationSpec,
    deal_id: str | None = None,
    recipient_user_id: str | None = None,
) -> str:
    row = conn.execute(
        """
        insert into notifications (org_id, deal_id, recipient_user_id, notification_type,
                                    severity, title, body, source_agent)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        returning notification_id
        """,
        (org_id, deal_id, recipient_user_id, spec.notification_type, spec.severity,
         spec.title, spec.body, spec.source_agent),
    ).fetchone()
    return str(row[0])


def list_notifications(conn: psycopg.Connection, org_id: str, unread_only: bool = False) -> list[dict]:
    query = "select * from notifications where org_id = %s"
    if unread_only:
        query += " and not is_read"
    query += " order by created_at desc"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (org_id,))
        return cur.fetchall()


def mark_notification_read(conn: psycopg.Connection, org_id: str, notification_id: str) -> bool:
    """Returns False if no matching (unread-or-read) notification exists for this org
    (including via RLS scoping to another org) — the caller turns that into a 404."""
    row = conn.execute(
        "update notifications set is_read = true, read_at = now() "
        "where org_id = %s and notification_id = %s returning notification_id",
        (org_id, notification_id),
    ).fetchone()
    return row is not None
