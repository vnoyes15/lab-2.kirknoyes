"""Rent roll parser — Section 16.

"Accepts PDF, Excel, CSV. Extracts per-unit data: unit ID, lease dates, contracted
rent, payment status. Aggregates to gross rent, vacancy rate, average rent, expiration
distribution. Flags 25%+ of leases expiring in any 60-day window."

Deterministic, no AI involved — same "pure Python over structured data" contract as
arx/validation. A-09 calls this module for document_type == "rent_roll" rather than
asking the model to read spreadsheet cells itself; the model is far more reliable at
unstructured prose (OMs, environmental reports) than at exact arithmetic over a table
it can already be parsed from mechanically.

INTERPRETATION NOTE on "gross_rent" for a rent roll specifically: the CRE glossary
(Section 02) defines gross rent as "total rent if every unit is occupied," but a rent
roll only records what's actually in place today. This parser reports gross_rent as
the sum of contracted rent across currently-occupied units (vacant units contribute
$0) — i.e. current in-place rent, not a hypothetical full-occupancy figure. A-02
combines this with the separately-tracked vacancy_rate to model potential income; it
does not need this parser to also guess a market rent for vacant units.

PDF SUPPORT NOTE: real-world rent roll PDFs vary enormously in layout. This first
version parses a simple, common convention — one unit per line, fields separated by
two-or-more spaces or a pipe character, following a header row — via PyMuPDF text
extraction. Anything it can't confidently parse as a unit row is skipped and surfaces
via `unparsed_line_count` rather than silently fabricated (N3).
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import fitz  # PyMuPDF
import openpyxl

EXPIRATION_WINDOW_DAYS = 60
EXPIRATION_FLAG_THRESHOLD = 0.25

VACANT_STATUS_VALUES = {"vacant", "vac", "empty"}


@dataclass
class UnitRecord:
    unit_id: str
    lease_start: date | None
    lease_end: date | None
    contracted_rent: float
    payment_status: str

    @property
    def is_vacant(self) -> bool:
        return self.payment_status.strip().lower() in VACANT_STATUS_VALUES


@dataclass
class RentRollSummary:
    units: list[UnitRecord]
    gross_rent: float
    vacancy_rate: float
    average_rent: float  # mean contracted rent among occupied units only
    expiration_flag: bool
    expiration_flag_detail: dict | None
    unparsed_line_count: int = 0


def _parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_rent(value) -> float:
    if value is None or value == "":
        return 0.0
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    return float(cleaned) if cleaned not in ("", "-", ".") else 0.0


def _summarize(units: list[UnitRecord], unparsed_line_count: int = 0) -> RentRollSummary:
    total_units = len(units)
    occupied = [u for u in units if not u.is_vacant]
    vacant_count = total_units - len(occupied)

    gross_rent = sum(u.contracted_rent for u in occupied)
    vacancy_rate = (vacant_count / total_units) if total_units else 0.0
    average_rent = (gross_rent / len(occupied)) if occupied else 0.0

    flag, detail = _check_expiration_concentration(occupied)

    return RentRollSummary(
        units=units,
        gross_rent=gross_rent,
        vacancy_rate=vacancy_rate,
        average_rent=average_rent,
        expiration_flag=flag,
        expiration_flag_detail=detail,
        unparsed_line_count=unparsed_line_count,
    )


def _check_expiration_concentration(occupied: list[UnitRecord]) -> tuple[bool, dict | None]:
    """Section 16: "Flags 25%+ of leases expiring in any 60-day window." Slides a
    60-day window starting at each distinct lease_end date present in the data (the
    only candidate window starts that could possibly capture a maximal cluster) and
    checks the fraction of occupied units expiring within it.
    """
    end_dates = sorted(u.lease_end for u in occupied if u.lease_end is not None)
    if not end_dates or not occupied:
        return False, None

    total_occupied = len(occupied)
    for window_start in end_dates:
        window_end = window_start + timedelta(days=EXPIRATION_WINDOW_DAYS)
        count = sum(1 for d in end_dates if window_start <= d < window_end)
        fraction = count / total_occupied
        if fraction >= EXPIRATION_FLAG_THRESHOLD:
            return True, {
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "expiring_count": count,
                "total_occupied": total_occupied,
                "fraction": fraction,
            }
    return False, None


def parse_csv(file_bytes: bytes) -> RentRollSummary:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    units = [
        UnitRecord(
            unit_id=str(row.get("unit_id", "")).strip(),
            lease_start=_parse_date(row.get("lease_start")),
            lease_end=_parse_date(row.get("lease_end")),
            contracted_rent=_parse_rent(row.get("contracted_rent")),
            payment_status=str(row.get("payment_status", "")).strip(),
        )
        for row in reader
    ]
    return _summarize(units)


def parse_excel(file_bytes: bytes) -> RentRollSummary:
    workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return _summarize([])

    header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    col = {name: idx for idx, name in enumerate(header)}
    required = {"unit_id", "lease_start", "lease_end", "contracted_rent", "payment_status"}
    missing = required - col.keys()
    if missing:
        raise ValueError(f"Rent roll Excel file missing required columns: {sorted(missing)}")

    units = []
    for row in rows[1:]:
        if row is None or all(cell is None for cell in row):
            continue
        units.append(UnitRecord(
            unit_id=str(row[col["unit_id"]]).strip() if row[col["unit_id"]] is not None else "",
            lease_start=_parse_date(row[col["lease_start"]]),
            lease_end=_parse_date(row[col["lease_end"]]),
            contracted_rent=_parse_rent(row[col["contracted_rent"]]),
            payment_status=str(row[col["payment_status"]]).strip() if row[col["payment_status"]] is not None else "",
        ))
    return _summarize(units)


_PDF_ROW_SPLIT = re.compile(r"\s{2,}|\|")


def parse_pdf(file_bytes: bytes) -> RentRollSummary:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        lines: list[str] = []
        for page in doc:
            lines.extend(page.get_text().splitlines())
    finally:
        doc.close()

    units: list[UnitRecord] = []
    unparsed_line_count = 0
    header_seen = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        fields = [f.strip() for f in _PDF_ROW_SPLIT.split(line) if f.strip()]
        if not header_seen:
            if len(fields) >= 4 and fields[0].strip().lower() in ("unit_id", "unit", "unit id"):
                header_seen = True
            continue
        if len(fields) < 5:
            unparsed_line_count += 1
            continue
        unit_id, lease_start, lease_end, contracted_rent, payment_status = fields[:5]
        units.append(UnitRecord(
            unit_id=unit_id,
            lease_start=_parse_date(lease_start),
            lease_end=_parse_date(lease_end),
            contracted_rent=_parse_rent(contracted_rent),
            payment_status=payment_status,
        ))

    return _summarize(units, unparsed_line_count=unparsed_line_count)


def parse_rent_roll(file_bytes: bytes, filename: str) -> RentRollSummary:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "csv":
        return parse_csv(file_bytes)
    if suffix in ("xlsx", "xlsm"):
        return parse_excel(file_bytes)
    if suffix == "pdf":
        return parse_pdf(file_bytes)
    raise ValueError(f"Unsupported rent roll file type: .{suffix}")
