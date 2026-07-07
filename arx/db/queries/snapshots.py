"""deal_snapshots helpers — Section 13 Deal Versioning, Section 04 R5.

"Every validated agent output creates an immutable snapshot... New snapshot never
auto-activates — user designates explicitly. Downstream agents always use the active
snapshot." write_snapshot() always inserts with is_active=False; a separate,
explicit activate_snapshot() call is required to make it the one downstream agents
and the API will read (arx/db/migrations/007_deal_snapshots.sql enforces this can
never silently double up via the partial unique index on (deal_id, agent_id) WHERE
is_active).
"""
import json

import psycopg
from psycopg.rows import dict_row


def next_version_number(conn: psycopg.Connection, deal_id: str, agent_id: str) -> int:
    row = conn.execute(
        "select coalesce(max(version_number), 0) + 1 as next_version "
        "from deal_snapshots where deal_id = %s and agent_id = %s",
        (deal_id, agent_id),
    ).fetchone()
    return row[0]


def write_snapshot(
    conn: psycopg.Connection,
    *,
    deal_id: str,
    org_id: str,
    agent_id: str,
    input_payload: dict,
    output_payload: dict,
    confidence_score: str | None,
    created_by_user_id: str | None = None,
) -> str:
    """Inserts a new, inactive snapshot and returns its snapshot_id. Never overwrites
    a prior version (Section 13) — always a new row at the next version_number."""
    version_number = next_version_number(conn, deal_id, agent_id)
    row = conn.execute(
        """
        insert into deal_snapshots (deal_id, org_id, agent_id, version_number, is_active,
                                     confidence_score, input_payload, output_payload, created_by_user_id)
        values (%s, %s, %s, %s, false, %s, %s, %s, %s)
        returning snapshot_id
        """,
        (deal_id, org_id, agent_id, version_number, confidence_score,
         json.dumps(input_payload), json.dumps(output_payload), created_by_user_id),
    ).fetchone()
    return str(row[0])


def activate_snapshot(conn: psycopg.Connection, *, deal_id: str, agent_id: str, snapshot_id: str) -> None:
    """R5: exactly one active snapshot per deal+agent. Deactivate whatever is
    currently active first — required because uq_deal_snapshots_active is a partial
    unique index enforced immediately, not a deferrable constraint."""
    conn.execute(
        "update deal_snapshots set is_active = false "
        "where deal_id = %s and agent_id = %s and is_active = true",
        (deal_id, agent_id),
    )
    conn.execute(
        "update deal_snapshots set is_active = true where snapshot_id = %s and deal_id = %s and agent_id = %s",
        (snapshot_id, deal_id, agent_id),
    )


def get_active_snapshot(conn: psycopg.Connection, *, deal_id: str, agent_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select * from deal_snapshots where deal_id = %s and agent_id = %s and is_active = true",
            (deal_id, agent_id),
        )
        return cur.fetchone()
