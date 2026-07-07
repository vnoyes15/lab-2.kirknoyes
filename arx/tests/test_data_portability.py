from datetime import date

import pytest

from arx.agents.data_portability import (
    parse_contact_row,
    parse_deal_performance_row,
    parse_deal_row,
    parse_lender_profile_row,
    parse_market_comp_row,
)


def test_parse_deal_row_happy_path():
    row = parse_deal_row({
        "property_address": "123 Main St", "source": "broker", "deal_type": "acquisition",
        "asking_price": "5000000", "unit_count": "24",
    })
    assert row.property_address == "123 Main St"
    assert row.asking_price == 5_000_000.0
    assert row.unit_count == 24


def test_parse_deal_row_missing_required_field_raises():
    with pytest.raises(ValueError, match="property_address"):
        parse_deal_row({"source": "broker", "deal_type": "acquisition"})


def test_parse_deal_row_invalid_deal_type_raises():
    with pytest.raises(ValueError, match="deal_type"):
        parse_deal_row({"property_address": "123 Main St", "source": "broker", "deal_type": "condo"})


def test_parse_deal_row_bad_number_raises():
    with pytest.raises(ValueError, match="asking_price"):
        parse_deal_row({
            "property_address": "123 Main St", "source": "broker", "deal_type": "acquisition",
            "asking_price": "not-a-number",
        })


def test_parse_contact_row_invalid_category_raises():
    with pytest.raises(ValueError, match="contact_category"):
        parse_contact_row({"name": "Jane Broker", "contact_category": "wizard"})


def test_parse_contact_row_happy_path():
    row = parse_contact_row({"name": "Jane Broker", "contact_category": "broker", "email": "jane@example.com"})
    assert row.name == "Jane Broker"
    assert row.email == "jane@example.com"


def test_parse_market_comp_row_happy_path():
    row = parse_market_comp_row({
        "submarket": "Tacoma", "cap_rate": "0.06", "sale_date": "2026-01-15", "source": "CoStar",
    })
    assert row.submarket == "Tacoma"
    assert row.cap_rate == pytest.approx(0.06)
    assert row.sale_date == date(2026, 1, 15)


def test_parse_market_comp_row_bad_date_raises():
    with pytest.raises(ValueError, match="sale_date"):
        parse_market_comp_row({"submarket": "Tacoma", "sale_date": "01/15/2026"})


def test_parse_lender_profile_row_splits_semicolon_lists():
    row = parse_lender_profile_row({
        "contact_name": "First National", "asset_types": "multifamily;office", "ltv_max": "0.75",
    })
    assert row.asset_types == ["multifamily", "office"]
    assert row.ltv_max == pytest.approx(0.75)


def test_parse_deal_performance_row_requires_period():
    with pytest.raises(ValueError, match="period"):
        parse_deal_performance_row({"property_address": "123 Main St", "actual_noi": "30000"})


def test_parse_deal_performance_row_happy_path():
    row = parse_deal_performance_row({
        "property_address": "123 Main St", "period": "2026-07-01", "actual_noi": "30000",
    })
    assert row.period == date(2026, 7, 1)
    assert row.actual_noi == pytest.approx(30_000)
