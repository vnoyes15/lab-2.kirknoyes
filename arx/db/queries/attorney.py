"""Attorney Portal — Section 71.

"Deal-specific access for ZONIQ's real estate attorney. Scope: view documents
relevant to their review, flag issues back into the deal record as deal_comments,
confirm completion of legal review items in A-06 checklist. Access granted per deal
by Admin. Attorney access does not include financial details, seller profiles,
outreach history."

Same curated-response discipline as arx/db/queries/lp.py's docstring explains: build
the attorney's view as an explicit allow-list, never a "fetch the deal, filter out the
bad parts" denylist, so a new column on `deals` can't leak to an attorney by accident.
"""
import psycopg
from psycopg.rows import dict_row

# Section 03's A-06 categories that are actually "legal review" in nature — not every
# DD category (e.g. physical_inspection, lease_audit) is something an attorney signs
# off on.
LEGAL_REVIEW_TASK_CATEGORIES = ("legal_and_title_review", "title_and_survey")


def has_attorney_access(conn: psycopg.Connection, *, deal_id: str, attorney_user_id: str) -> bool:
    row = conn.execute(
        "select 1 from deal_attorney_access where deal_id = %s and attorney_user_id = %s",
        (deal_id, attorney_user_id),
    ).fetchone()
    return row is not None


def grant_attorney_access(
    conn: psycopg.Connection, *, deal_id: str, org_id: str, attorney_user_id: str, granted_by_user_id: str,
) -> str:
    row = conn.execute(
        """
        insert into deal_attorney_access (deal_id, org_id, attorney_user_id, granted_by_user_id)
        values (%s, %s, %s, %s)
        on conflict (deal_id, attorney_user_id) do update set granted_at = now()
        returning access_id
        """,
        (deal_id, org_id, attorney_user_id, granted_by_user_id),
    ).fetchone()
    return str(row[0])


def list_attorney_accessible_deals(conn: psycopg.Connection, attorney_user_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select d.deal_id, d.property_address, d.deal_type, d.status
            from deals d
            inner join deal_attorney_access a on a.deal_id = d.deal_id
            where a.attorney_user_id = %s
            """,
            (attorney_user_id,),
        )
        return cur.fetchall()


def get_attorney_deal_view(conn: psycopg.Connection, deal_id: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select deal_id, property_address, deal_type, status from deals where deal_id = %s", (deal_id,),
        )
        deal = cur.fetchone()

        cur.execute(
            "select doc_id, doc_type, filename, version, uploaded_by, created_at "
            "from documents where deal_id = %s order by created_at",
            (deal_id,),
        )
        documents = cur.fetchall()

        cur.execute(
            "select task_id, title, description, status, due_date "
            "from deal_tasks where deal_id = %s and source_agent = 'a06' "
            "and (title like %s or title like %s) "
            "order by created_at",
            (deal_id, "DD: legal_and_title_review%", "DD: title_and_survey%"),
        )
        legal_review_items = cur.fetchall()

    return {
        "deal_id": deal["deal_id"], "property_address": deal["property_address"],
        "deal_type": deal["deal_type"], "status": deal["status"],
        "documents": documents,
        "legal_review_items": legal_review_items,
    }


def confirm_legal_review_task(conn: psycopg.Connection, *, deal_id: str, task_id: str) -> dict | None:
    """Only a task that's actually a legal-review DD item can be confirmed here —
    an attorney's access doesn't extend to marking arbitrary tasks (physical
    inspection, lease audit, etc.) complete."""
    row = conn.execute(
        "select title from deal_tasks where task_id = %s and deal_id = %s and source_agent = 'a06'",
        (task_id, deal_id),
    ).fetchone()
    if row is None:
        return None
    title = row[0]
    if not any(title.startswith(f"DD: {category}") for category in LEGAL_REVIEW_TASK_CATEGORIES):
        return None

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "update deal_tasks set status = 'complete', completed_at = now() "
            "where task_id = %s returning task_id, title, status, completed_at",
            (task_id,),
        )
        return cur.fetchone()


def create_deal_comment(
    conn: psycopg.Connection, *, deal_id: str, org_id: str, author_user_id: str, author_role: str, body: str,
) -> str:
    row = conn.execute(
        """
        insert into deal_comments (deal_id, org_id, author_user_id, author_role, body)
        values (%s, %s, %s, %s, %s)
        returning comment_id
        """,
        (deal_id, org_id, author_user_id, author_role, body),
    ).fetchone()
    return str(row[0])


def list_deal_comments(conn: psycopg.Connection, deal_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select * from deal_comments where deal_id = %s order by created_at desc", (deal_id,),
        )
        return cur.fetchall()
