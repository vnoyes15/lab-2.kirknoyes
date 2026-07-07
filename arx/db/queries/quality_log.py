"""agent_quality_log / error_log helpers — Section 12 Observability, Section 10 Error
Handling, Section 78 Error Response Protocol.

Every agent run records exactly one agent_quality_log row (success or failure).
Failures additionally write a full error_log record (EH4: "All unrecoverable errors
write to error_log with full input payload and raw model output.").
"""
import json

import psycopg
from psycopg.rows import dict_row


def record_agent_run(
    conn: psycopg.Connection,
    *,
    org_id: str,
    deal_id: str | None,
    agent_id: str,
    prompt_version: str | None,
    confidence_score: str | None,
    validation_passed: bool,
    failed_checks: dict | None,
    token_count: int | None,
) -> None:
    conn.execute(
        """
        insert into agent_quality_log (org_id, deal_id, agent_id, prompt_version,
                                        confidence_score, validation_passed, failed_checks, token_count)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (org_id, deal_id, agent_id, prompt_version, confidence_score, validation_passed,
         json.dumps(failed_checks) if failed_checks is not None else None, token_count),
    )


def record_error(
    conn: psycopg.Connection,
    *,
    org_id: str,
    deal_id: str | None,
    error_type: str,
    agent_id: str | None,
    step: str | None,
    input_payload: dict | None,
    raw_output: str | None,
    failed_checks: dict | None,
) -> str:
    row = conn.execute(
        """
        insert into error_log (org_id, deal_id, error_type, agent_id, step, input_payload, raw_output, failed_checks)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        returning error_id
        """,
        (org_id, deal_id, error_type, agent_id, step,
         json.dumps(input_payload) if input_payload is not None else None,
         raw_output,
         json.dumps(failed_checks) if failed_checks is not None else None),
    ).fetchone()
    return str(row[0])


def list_errors(conn: psycopg.Connection, org_id: str, resolution_status: str | None = None) -> list[dict]:
    """Section 78 EP2: errors are tracked through to closure, not just written once and
    forgotten — this is the list an Admin works from."""
    query = "select * from error_log where org_id = %s"
    params: list = [org_id]
    if resolution_status is not None:
        query += " and resolution_status = %s"
        params.append(resolution_status)
    query += " order by created_at desc"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def update_error_resolution(
    conn: psycopg.Connection, *, org_id: str, error_id: str, resolution_status: str, resolution_notes: str | None,
) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "update error_log set resolution_status = %s, resolution_notes = %s "
            "where org_id = %s and error_id = %s returning *",
            (resolution_status, resolution_notes, org_id, error_id),
        )
        return cur.fetchone()
