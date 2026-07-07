"""equity_waterfalls persistence — Section 70. Pairs with the pure math in
arx/agents/equity_waterfall.py the same way scenario models pair with
scenario_modeling.py: this module only writes/reads, it never computes.
"""
import json

import psycopg
from psycopg.rows import dict_row


def record_equity_waterfall(
    conn: psycopg.Connection, *,
    deal_id: str, org_id: str, structure_type: str, inputs: dict, outputs: dict,
    created_by_user_id: str | None,
) -> str:
    row = conn.execute(
        """
        insert into equity_waterfalls (deal_id, org_id, structure_type, inputs, outputs, created_by_user_id)
        values (%s, %s, %s, %s, %s, %s)
        returning waterfall_id
        """,
        (deal_id, org_id, structure_type, json.dumps(inputs), json.dumps(outputs), created_by_user_id),
    ).fetchone()
    return str(row[0])


def list_equity_waterfalls(conn: psycopg.Connection, deal_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select * from equity_waterfalls where deal_id = %s order by created_at desc", (deal_id,),
        )
        return cur.fetchall()
