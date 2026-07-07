"""Cost Controls — Section 11.

"Soft warning at 80% of monthly org budget. Hard ceiling at 100% — all agent calls
blocked. Budget check before API call. Token count and database write in same
transaction."
"""
from dataclasses import dataclass

import psycopg

SOFT_WARNING_THRESHOLD = 0.80


@dataclass(frozen=True)
class BudgetStatus:
    token_used_this_month: int
    token_budget_monthly: int
    blocked: bool
    warning: bool

    @property
    def fraction_used(self) -> float:
        return self.token_used_this_month / self.token_budget_monthly if self.token_budget_monthly else 1.0


def check_budget(conn: psycopg.Connection, org_id: str) -> BudgetStatus:
    row = conn.execute(
        "select token_used_this_month, token_budget_monthly from orgs where org_id = %s", (org_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"org {org_id} not found")
    used, budget = row
    return BudgetStatus(
        token_used_this_month=used,
        token_budget_monthly=budget,
        blocked=used >= budget,
        warning=used >= budget * SOFT_WARNING_THRESHOLD,
    )


def increment_token_usage(conn: psycopg.Connection, org_id: str, tokens: int) -> None:
    conn.execute(
        "update orgs set token_used_this_month = token_used_this_month + %s where org_id = %s",
        (tokens, org_id),
    )
