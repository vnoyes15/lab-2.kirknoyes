"""Integration tests for Section 74 Data Portability & Migration against a live
Postgres + FastAPI app. Skipped automatically if no DATABASE_URL is reachable.
"""
import io
import json
import time
import zipfile

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
            "insert into orgs (org_name, token_budget_monthly) values ('TEST_DATA_PORT_ORG', 500000) returning org_id"
        ).fetchone()[0])
        yield _org_id
    finally:
        if _org_id:
            with conn.transaction():
                conn.execute("set local arx.allow_snapshot_delete = 'true'")
                conn.execute("delete from orgs where org_id = %s", (_org_id,))
        conn.close()


@pytest.fixture
def client_and_token(org_id):
    from arx.api.main import app
    return TestClient(app), _mint_token(org_id)


def _upload_csv(client, token, resource_type, csv_text):
    return client.post(
        f"/api/v1/import/{resource_type}",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("data.csv", csv_text, "text/csv")},
    )


def test_import_deals_happy_path(client_and_token):
    client, token = client_and_token
    csv_text = (
        "property_address,source,deal_type,asking_price,unit_count\n"
        "123 Main St,broker,acquisition,5000000,24\n"
        "456 Oak Ave,cold_call,land,1200000,\n"
    )
    resp = _upload_csv(client, token, "deals", csv_text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 2
    assert body["duplicates_skipped"] == 0
    assert body["errors"] == []


def test_import_deals_deduplicates_and_reports_bad_rows(client_and_token):
    client, token = client_and_token
    resp1 = _upload_csv(
        client, token, "deals",
        "property_address,source,deal_type,asking_price\n123 Main St,broker,acquisition,5000000\n",
    )
    assert resp1.json()["imported"] == 1

    csv_text = (
        "property_address,source,deal_type,asking_price\n"
        "123 Main St,broker,acquisition,5000000\n"  # duplicate address
        "789 Pine St,broker,condo,1000000\n"  # invalid deal_type
        "999 Elm St,broker,acquisition,not-a-number\n"  # bad number
        "555 Cedar St,broker,acquisition,3000000\n"  # valid new row
    )
    resp2 = _upload_csv(client, token, "deals", csv_text)
    assert resp2.status_code == 200, resp2.text
    body = resp2.json()
    assert body["imported"] == 1
    assert body["duplicates_skipped"] == 1
    assert len(body["errors"]) == 2
    assert body["errors"][0]["row"] == 3  # 789 Pine St is CSV row 3 (header=1, first data row=2)


def test_import_unknown_resource_type_400s(client_and_token):
    client, token = client_and_token
    resp = _upload_csv(client, token, "spaceships", "a,b\n1,2\n")
    assert resp.status_code == 400


def test_import_contacts_happy_path_and_dedup(client_and_token, org_id):
    client, token = client_and_token
    csv_text = "name,contact_category,email\nJane Broker,broker,jane@example.com\n"
    resp1 = _upload_csv(client, token, "contacts", csv_text)
    assert resp1.json()["imported"] == 1
    resp2 = _upload_csv(client, token, "contacts", csv_text)
    assert resp2.json()["duplicates_skipped"] == 1

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select contact_info from contacts where org_id = %s and name = 'Jane Broker'", (org_id,)
    ).fetchone()
    conn.close()
    assert row[0]["email"] == "jane@example.com"


def test_import_market_comps(client_and_token):
    client, token = client_and_token
    csv_text = "submarket,cap_rate,sale_date,source\nTacoma,0.06,2026-01-15,CoStar\n"
    resp = _upload_csv(client, token, "market_comps", csv_text)
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 1


def test_import_lender_profiles_creates_contact_and_profile(client_and_token, org_id):
    client, token = client_and_token
    csv_text = "contact_name,asset_types,ltv_max\nFirst National,multifamily;office,0.75\n"
    resp = _upload_csv(client, token, "lender_profiles", csv_text)
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 1

    conn = psycopg.connect(settings.database_url, autocommit=True)
    row = conn.execute(
        "select lp.ltv_max, lp.asset_types from lender_profiles lp "
        "join contacts c on c.contact_id = lp.contact_id where c.org_id = %s and c.name = 'First National'",
        (org_id,),
    ).fetchone()
    conn.close()
    assert float(row[0]) == pytest.approx(0.75)
    assert row[1] == ["multifamily", "office"]


def test_import_deal_performance_requires_existing_deal(client_and_token):
    client, token = client_and_token
    resp = _upload_csv(
        client, token, "deal_performance",
        "property_address,period,actual_noi\nNonexistent St,2026-07-01,30000\n",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 0
    assert len(body["errors"]) == 1
    assert "no deal found" in body["errors"][0]["error"]


def test_import_deal_performance_dedups_on_period(client_and_token):
    client, token = client_and_token
    _upload_csv(
        client, token, "deals",
        "property_address,source,deal_type,asking_price\n123 Main St,broker,acquisition,5000000\n",
    )
    csv_text = "property_address,period,actual_noi\n123 Main St,2026-07-01,30000\n"
    resp1 = _upload_csv(client, token, "deal_performance", csv_text)
    assert resp1.json()["imported"] == 1
    resp2 = _upload_csv(client, token, "deal_performance", csv_text)
    assert resp2.json()["duplicates_skipped"] == 1


def test_analyst_cannot_export(client_and_token):
    client, token = client_and_token
    resp = client.get("/api/v1/export", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_admin_export_json_includes_imported_deal(org_id):
    from arx.api.main import app
    client = TestClient(app)
    analyst_token = _mint_token(org_id, "analyst")
    _upload_csv(
        client, analyst_token, "deals",
        "property_address,source,deal_type,asking_price\n123 Main St,broker,acquisition,5000000\n",
    )

    admin_token = _mint_token(org_id, "admin")
    resp = client.get("/api/v1/export?format=json", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200, resp.text
    body = json.loads(resp.content)
    assert any(d["property_address"] == "123 Main St" for d in body["deals"])


def test_admin_export_csv_returns_zip_with_deals_csv(org_id):
    from arx.api.main import app
    client = TestClient(app)
    analyst_token = _mint_token(org_id, "analyst")
    _upload_csv(
        client, analyst_token, "deals",
        "property_address,source,deal_type,asking_price\n123 Main St,broker,acquisition,5000000\n",
    )

    admin_token = _mint_token(org_id, "admin")
    resp = client.get("/api/v1/export?format=csv", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert "deals.csv" in zf.namelist()
    deals_csv = zf.read("deals.csv").decode("utf-8")
    assert "123 Main St" in deals_csv
