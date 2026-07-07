"""Data Portability & Migration — Section 74.

"Deal records, contacts, market comps, lender profiles, historical deal performance —
all importable via CSV with defined schemas. Import validation: data type checks,
deduplication against existing records, error report for failing rows. Failed rows do
not block valid rows."

"All deal data, financial records, snapshots, documents, and performance history
exportable as structured CSV or JSON. Operators own their data. Arx does not hold data
hostage. Full export available at any time to Admin role."

Pure per-row validation/normalization functions, no DB — same "decide what's valid,
never touch a connection" split as the rest of this package. arx/db/queries/
data_portability.py does the actual inserts/dedup/lookups per row using these.
"""
from dataclasses import dataclass
from datetime import date

DEAL_TYPES = ("acquisition", "land", "development")
CONTACT_CATEGORIES = ("seller", "broker", "lender", "lp", "attorney", "property_manager", "other")

IMPORT_RESOURCE_TYPES = ("deals", "contacts", "market_comps", "lender_profiles", "deal_performance")


def _require(row: dict, field: str) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise ValueError(f"missing required field '{field}'")
    return value


def _optional_float(row: dict, field: str) -> float | None:
    value = (row.get(field) or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"field '{field}' must be a number, got {value!r}")


def _optional_int(row: dict, field: str) -> int | None:
    value = (row.get(field) or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"field '{field}' must be an integer, got {value!r}")


def _optional_date(row: dict, field: str) -> date | None:
    value = (row.get(field) or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"field '{field}' must be an ISO date (YYYY-MM-DD), got {value!r}")


def _optional_list(row: dict, field: str) -> list[str] | None:
    value = (row.get(field) or "").strip()
    return [v.strip() for v in value.split(";") if v.strip()] or None


@dataclass(frozen=True)
class ParsedDealRow:
    property_address: str
    source: str
    deal_type: str
    asking_price: float | None
    unit_count: int | None
    land_area_sf: float | None
    asset_type: str | None


def parse_deal_row(row: dict) -> ParsedDealRow:
    deal_type = _require(row, "deal_type")
    if deal_type not in DEAL_TYPES:
        raise ValueError(f"deal_type must be one of {DEAL_TYPES}, got {deal_type!r}")
    return ParsedDealRow(
        property_address=_require(row, "property_address"), source=_require(row, "source"), deal_type=deal_type,
        asking_price=_optional_float(row, "asking_price"), unit_count=_optional_int(row, "unit_count"),
        land_area_sf=_optional_float(row, "land_area_sf"), asset_type=(row.get("asset_type") or "").strip() or None,
    )


@dataclass(frozen=True)
class ParsedContactRow:
    name: str
    contact_category: str
    role_type: str | None
    email: str | None
    phone: str | None


def parse_contact_row(row: dict) -> ParsedContactRow:
    contact_category = _require(row, "contact_category")
    if contact_category not in CONTACT_CATEGORIES:
        raise ValueError(f"contact_category must be one of {CONTACT_CATEGORIES}, got {contact_category!r}")
    return ParsedContactRow(
        name=_require(row, "name"), contact_category=contact_category,
        role_type=(row.get("role_type") or "").strip() or None,
        email=(row.get("email") or "").strip() or None, phone=(row.get("phone") or "").strip() or None,
    )


@dataclass(frozen=True)
class ParsedMarketCompRow:
    submarket: str
    asset_type: str | None
    cap_rate: float | None
    price_per_unit: float | None
    sale_date: date | None
    source: str | None


def parse_market_comp_row(row: dict) -> ParsedMarketCompRow:
    return ParsedMarketCompRow(
        submarket=_require(row, "submarket"), asset_type=(row.get("asset_type") or "").strip() or None,
        cap_rate=_optional_float(row, "cap_rate"), price_per_unit=_optional_float(row, "price_per_unit"),
        sale_date=_optional_date(row, "sale_date"), source=(row.get("source") or "").strip() or None,
    )


@dataclass(frozen=True)
class ParsedLenderProfileRow:
    contact_name: str
    asset_types: list[str] | None
    loan_types: list[str] | None
    target_markets: list[str] | None
    ltv_max: float | None
    ltc_max: float | None
    dscr_threshold: float | None
    last_deal_date: date | None
    relationship_notes: str | None


def parse_lender_profile_row(row: dict) -> ParsedLenderProfileRow:
    return ParsedLenderProfileRow(
        contact_name=_require(row, "contact_name"),
        asset_types=_optional_list(row, "asset_types"), loan_types=_optional_list(row, "loan_types"),
        target_markets=_optional_list(row, "target_markets"),
        ltv_max=_optional_float(row, "ltv_max"), ltc_max=_optional_float(row, "ltc_max"),
        dscr_threshold=_optional_float(row, "dscr_threshold"),
        last_deal_date=_optional_date(row, "last_deal_date"),
        relationship_notes=(row.get("relationship_notes") or "").strip() or None,
    )


@dataclass(frozen=True)
class ParsedDealPerformanceRow:
    property_address: str
    period: date
    actual_gross_rent: float | None
    actual_vacancy_rate: float | None
    actual_noi: float | None
    actual_operating_expenses: float | None


def parse_deal_performance_row(row: dict) -> ParsedDealPerformanceRow:
    period = _optional_date(row, "period")
    if period is None:
        raise ValueError("missing required field 'period'")
    return ParsedDealPerformanceRow(
        property_address=_require(row, "property_address"), period=period,
        actual_gross_rent=_optional_float(row, "actual_gross_rent"),
        actual_vacancy_rate=_optional_float(row, "actual_vacancy_rate"),
        actual_noi=_optional_float(row, "actual_noi"),
        actual_operating_expenses=_optional_float(row, "actual_operating_expenses"),
    )
