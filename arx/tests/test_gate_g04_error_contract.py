"""Gate G-04 — Section 14: "All defined failure scenarios return correct structured
errors — no silent failures across all 13 agents."

Per-agent unit tests (test_a0X_*.py) already prove each agent's own validation logic
raises the right XXValidationError for that agent's specific failure modes. This gate
proves the uniform *contract* holds at the API layer for every one of the 13 agents:
a model response that fails Section 87 schema validation must come back as a
structured 422 (never a silent 200, never an unhandled 500) with a real error_id, and
must actually persist a error_log row (Section 10 EH4) — not just look persisted (see
arx/tests/test_db_session_error_commit.py for the regression this specifically
guards against). An empty object `{}` fails required-field validation for every one of
the 13 agents' output schemas, so it's the one deliberately-invalid response reused
across all of them here.
"""
import time

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from arx.agents.loan_math import compute_annual_debt_service
from arx.agents.model_client import model_client_dependency
from arx.api.config import get_settings
from arx.tests.fakes import FakeModelClient

PURCHASE_PRICE = 5_000_000
LOAN_AMOUNT, LTV, INTEREST_RATE, AMORT_YEARS = 3_750_000, 0.75, 0.065, 30
NOI = 300_000
ANNUAL_DEBT_SERVICE = compute_annual_debt_service(LOAN_AMOUNT, INTEREST_RATE, AMORT_YEARS)
DSCR = NOI / ANNUAL_DEBT_SERVICE
COC = (NOI - ANNUAL_DEBT_SERVICE) / (PURCHASE_PRICE * (1 - LTV))

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
        _org_id = str(conn.execute(
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_G04_ORG', 500000) returning org_id"
        ).fetchone()[0])
        conn.execute(
            "insert into org_jurisdictions (org_id, state_code, rent_control_active, "
            "rent_control_cap_formula, attorney_review_required) values (%s, 'WA', true, "
            "'7%% + CPI, or 10%%, whichever is lower', true)",
            (_org_id,),
        )
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
            "values (%s, '123 Main St', 'acquisition', 'lead', 5000000) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def contact_id(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        row = conn.execute(
            "insert into contacts (org_id, name, contact_category) values (%s, 'J. Smith', 'seller') returning contact_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def _activate_snapshot(client, token, deal_id, agent_id, fake):
    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"}, json={},
        )
        assert resp.status_code == 200, resp.text
        snapshot_id = resp.json()["snapshot_id"]
        activate = client.post(
            f"/api/v1/deals/{deal_id}/agents/{agent_id}/snapshots/{snapshot_id}/activate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert activate.status_code == 200
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)


@pytest.fixture
def with_active_a02(client_and_token, deal_id, org_id):
    """a04/a07/a12 all need an active A-02 snapshot before their own schema-validation
    failure path is even reachable — set that up first so this gate test exercises the
    thing it's meant to (a bad model response), not an unrelated precondition 409."""
    client, token = client_and_token
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into uw_config (org_id, track, version, is_active, config) values (%s, 'acquisition', 1, true, %s)",
        (org_id, '{"vacancy": 0.07, "ltv": 0.75, "interest_rate": 0.065, "amortization_years": 30}'),
    )
    conn.close()
    scenario = lambda cap_rate: {"cap_rate": cap_rate, "dscr": DSCR, "coc": COC}
    _activate_snapshot(client, token, deal_id, "a02", FakeModelClient({
        "gross_rent": 500_000, "vacancy_rate": 0.07, "vacancy_amount": 35_000,
        "operating_expenses": {"management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
                                "insurance": 25_000, "taxes": 40_000, "other": 10_000},
        "noi": NOI, "cap_rate": NOI / PURCHASE_PRICE, "dscr": DSCR, "cash_on_cash": COC,
        "sensitivity_table": {
            "rent_-10pct": scenario(0.052), "rent_-5pct": scenario(0.056), "base": scenario(0.06),
            "rent_+5pct": scenario(0.064), "rent_+10pct": scenario(0.068),
        },
        "load_bearing_assumptions": [{"assumption": "x", "why_it_matters": "y"}] * 3,
        "assumption_sources": {"gross_rent": "user_provided"}, "confidence_score": "high",
        "no_comp_disclaimer": None,
    }))
    return deal_id


@pytest.fixture
def with_active_acquisition_uw_config(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into uw_config (org_id, track, version, is_active, config) values (%s, 'acquisition', 1, true, %s)",
        (org_id, '{"vacancy": 0.07, "ltv": 0.75, "interest_rate": 0.065, "amortization_years": 30}'),
    )
    conn.close()


@pytest.fixture
def with_active_development_uw_config(org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    conn.execute(
        "insert into uw_config (org_id, track, version, is_active, config) values (%s, 'development', 1, true, %s)",
        (org_id, '{"soft_costs_pct_of_hard_min": 0.15, "soft_costs_pct_of_hard_max": 0.20}'),
    )
    conn.close()


AGENT_PAYLOADS = {
    "a01": {}, "a02": {}, "a04": {"seller_profile": {}},
    "a05": {"state_code": "WA", "selected_offer_strategy": {}},
    "a06": {"dd_track": "acquisition"}, "a07": {},
    "a10": {}, "a11": {"land_cost": 100_000, "exit_cap_rate": 0.06},
    "a12": {"original_offer_strategy": {}, "seller_counter_terms": {}}, "a13": {},
}
# Agents whose schema-validation failure path is only reachable once a precondition
# (an active uw_config or active upstream snapshot) is met — the fixture name to
# request for each, applied dynamically below.
AGENT_PRECONDITIONS = {
    "a02": "with_active_acquisition_uw_config",
    "a04": "with_active_a02", "a07": "with_active_a02", "a12": "with_active_a02",
    "a11": "with_active_development_uw_config",
}


@pytest.mark.parametrize("agent_id", sorted(AGENT_PAYLOADS.keys()))
def test_empty_model_response_yields_structured_422_and_error_log_row(
    request, client_and_token, deal_id, org_id, agent_id,
):
    if agent_id in AGENT_PRECONDITIONS:
        request.getfixturevalue(AGENT_PRECONDITIONS[agent_id])

    client, token = client_and_token
    fake = FakeModelClient({})

    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/{agent_id}",
            headers={"Authorization": f"Bearer {token}"}, json=AGENT_PAYLOADS[agent_id],
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)

    assert resp.status_code == 422, f"{agent_id}: expected 422, got {resp.status_code}: {resp.text}"
    body = resp.json()
    error_id = body["detail"]["error_id"] if isinstance(body["detail"], dict) else None
    assert error_id, f"{agent_id}: no error_id in response body: {body}"

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select error_id from error_log where org_id = %s and error_id = %s", (org_id, error_id)
    ).fetchone()
    conn.close()
    assert row is not None, f"{agent_id}: error_log row for {error_id} was not persisted"


def test_a03_requires_known_contact_structured_404(client_and_token, deal_id):
    """A-03 has no schema-failure path reachable via {} (recipient checks happen
    before the model call) — its defined failure mode is an unknown contact_id."""
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/agents/a03",
        headers={"Authorization": f"Bearer {token}"},
        json={"contact_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404


def test_a08_suppressed_contact_structured_403(client_and_token, deal_id, org_id):
    conn = psycopg.connect(settings.database_url, autocommit=True)
    contact_id = conn.execute(
        "insert into contacts (org_id, name, contact_category, suppressed, suppressed_at) "
        "values (%s, 'Do Not Contact', 'seller', true, now()) returning contact_id",
        (org_id,),
    ).fetchone()[0]
    conn.close()

    client, token = client_and_token
    fake = FakeModelClient({
        "message_text": "Hi, I'm reaching out about a potential acquisition in your area. " * 2,
        "channel": "email", "can_spam_placeholder": "[SENDER PHYSICAL ADDRESS]",
    })
    from arx.api.main import app
    app.dependency_overrides[model_client_dependency] = lambda: fake
    try:
        resp = client.post(
            f"/api/v1/deals/{deal_id}/agents/a08",
            headers={"Authorization": f"Bearer {token}"},
            json={"contact_id": str(contact_id), "recipient_type": "seller", "channel": "email"},
        )
    finally:
        app.dependency_overrides.pop(model_client_dependency, None)

    assert resp.status_code == 403
    assert len(fake.calls) == 0  # suppression is checked before any model call — Section 22
    body = resp.json()
    assert body["detail"]["error_id"]

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select count(*) from error_log where org_id = %s and error_type = 'suppressed_contact'", (org_id,)
    ).fetchone()
    conn.close()
    assert row[0] == 1
