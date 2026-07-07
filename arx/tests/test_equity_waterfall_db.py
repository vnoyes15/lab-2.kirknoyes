"""Integration tests for Section 70 JV & Complex Equity Structure Modeling against a
live Postgres + FastAPI app. Skipped automatically if no DATABASE_URL is reachable.
"""
import time

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from arx.api.config import get_settings

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
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_WATERFALL_ORG', 500000) returning org_id"
        ).fetchone()[0])
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
            "values (%s, '123 Main St', 'acquisition', 'closed', 5000000) returning deal_id",
            (org_id,),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def test_simple_lp_gp_waterfall_persists_and_returns_tiers(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/waterfall",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "structure_type": "simple_lp_gp", "lp_capital": 800_000, "gp_capital": 200_000,
            "total_distributable_proceeds": 2_000_000, "hurdle_moic": 1.5,
            "base_split_lp_pct": 0.8, "base_split_gp_pct": 0.2,
            "promote_split_lp_pct": 0.7, "promote_split_gp_pct": 0.3,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["structure_type"] == "simple_lp_gp"
    assert body["lp_total_distribution"] + body["gp_total_distribution"] == pytest.approx(2_000_000)
    assert len(body["tiers"]) == 3


def test_preferred_equity_waterfall_persists(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/waterfall",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "structure_type": "preferred_equity", "lp_capital": 800_000, "gp_capital": 200_000,
            "total_distributable_proceeds": 1_500_000, "pref_rate": 0.08, "hold_period_years": 5,
            "catch_up_pct": 0.20, "residual_split_lp_pct": 0.8, "residual_split_gp_pct": 0.2,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["lp_total_distribution"] + body["gp_total_distribution"] == pytest.approx(1_500_000)


def test_jv_co_gp_waterfall_splits_gp_profit(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/waterfall",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "structure_type": "jv_co_gp", "lp_capital": 800_000, "gp_capital": 200_000,
            "total_distributable_proceeds": 2_000_000, "hurdle_moic": 1.5,
            "base_split_lp_pct": 0.8, "base_split_gp_pct": 0.2,
            "promote_split_lp_pct": 0.7, "promote_split_gp_pct": 0.3,
            "co_gp_shares": {"ZONIQ": 0.6, "Partner": 0.4},
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    breakdown = body["co_gp_breakdown"]
    assert breakdown["ZONIQ"] + breakdown["Partner"] == pytest.approx(body["gp_total_distribution"])
    assert breakdown["ZONIQ"] == pytest.approx(body["gp_total_distribution"] * 0.6)


def test_mezzanine_waterfall_reduces_equity_pool(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/waterfall",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "structure_type": "mezzanine", "lp_capital": 800_000, "gp_capital": 200_000,
            "total_distributable_proceeds": 2_000_000, "mezz_principal": 300_000, "mezz_rate": 0.10,
            "mezz_term_years": 3, "hurdle_moic": 1.5,
            "base_split_lp_pct": 0.8, "base_split_gp_pct": 0.2,
            "promote_split_lp_pct": 0.7, "promote_split_gp_pct": 0.3,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mezz_total_repayment"] == pytest.approx(300_000 * 1.10 ** 3)
    assert body["lp_total_distribution"] + body["gp_total_distribution"] == pytest.approx(
        body["equity_distributable_proceeds"]
    )


def test_ground_lease_waterfall_reduces_leasehold_pool(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/waterfall",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "structure_type": "ground_lease", "lp_capital": 800_000, "gp_capital": 200_000,
            "total_distributable_proceeds": 2_000_000, "ground_rent_annual": 40_000, "lease_term_years": 10,
            "hurdle_moic": 1.5,
            "base_split_lp_pct": 0.8, "base_split_gp_pct": 0.2,
            "promote_split_lp_pct": 0.7, "promote_split_gp_pct": 0.3,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["total_ground_rent_paid"] == pytest.approx(400_000)
    assert body["leasehold_distributable_proceeds"] == pytest.approx(1_600_000)


def test_waterfall_unknown_deal_404s(client_and_token):
    client, token = client_and_token
    resp = client.post(
        "/api/v1/deals/00000000-0000-0000-0000-000000000000/waterfall",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "structure_type": "simple_lp_gp", "lp_capital": 800_000, "gp_capital": 200_000,
            "total_distributable_proceeds": 2_000_000, "hurdle_moic": 1.5,
            "base_split_lp_pct": 0.8, "base_split_gp_pct": 0.2,
            "promote_split_lp_pct": 0.7, "promote_split_gp_pct": 0.3,
        },
    )
    assert resp.status_code == 404


def test_waterfall_bad_split_ratio_returns_422(client_and_token, deal_id):
    client, token = client_and_token
    resp = client.post(
        f"/api/v1/deals/{deal_id}/waterfall",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "structure_type": "simple_lp_gp", "lp_capital": 800_000, "gp_capital": 200_000,
            "total_distributable_proceeds": 2_000_000, "hurdle_moic": 1.5,
            "base_split_lp_pct": 0.8, "base_split_gp_pct": 0.5,  # doesn't sum to 1.0
            "promote_split_lp_pct": 0.7, "promote_split_gp_pct": 0.3,
        },
    )
    assert resp.status_code == 422


def test_list_waterfalls_returns_prior_runs(client_and_token, deal_id):
    client, token = client_and_token
    payload = {
        "structure_type": "simple_lp_gp", "lp_capital": 800_000, "gp_capital": 200_000,
        "total_distributable_proceeds": 2_000_000, "hurdle_moic": 1.5,
        "base_split_lp_pct": 0.8, "base_split_gp_pct": 0.2,
        "promote_split_lp_pct": 0.7, "promote_split_gp_pct": 0.3,
    }
    client.post(f"/api/v1/deals/{deal_id}/waterfall", headers={"Authorization": f"Bearer {token}"}, json=payload)
    resp = client.get(f"/api/v1/deals/{deal_id}/waterfall", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1
