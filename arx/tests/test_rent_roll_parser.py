import io

import fitz
import openpyxl
import pytest

from arx.agents.rent_roll_parser import parse_csv, parse_excel, parse_pdf, parse_rent_roll

CSV_SAMPLE = """unit_id,lease_start,lease_end,contracted_rent,payment_status
101,2025-01-01,2026-01-01,1500,current
102,2025-02-01,2026-02-01,1450,current
103,2025-03-01,2026-03-01,0,vacant
104,2025-04-01,2026-04-01,1600,current
""".encode("utf-8")


def test_parse_csv_basic_aggregation():
    summary = parse_csv(CSV_SAMPLE)
    assert len(summary.units) == 4
    assert summary.vacancy_rate == pytest.approx(0.25)  # 1 of 4 vacant
    assert summary.gross_rent == pytest.approx(1500 + 1450 + 1600)
    assert summary.average_rent == pytest.approx((1500 + 1450 + 1600) / 3)


def test_parse_csv_no_vacant_units():
    csv_bytes = (
        "unit_id,lease_start,lease_end,contracted_rent,payment_status\n"
        "1,2025-01-01,2026-01-01,1000,current\n"
        "2,2025-01-01,2026-01-01,1000,current\n"
    ).encode("utf-8")
    summary = parse_csv(csv_bytes)
    assert summary.vacancy_rate == 0.0
    assert summary.gross_rent == 2000


def test_expiration_concentration_flag_triggers():
    # 3 of 4 occupied units expire within the same 60-day window -> 75% >= 25% threshold.
    csv_bytes = (
        "unit_id,lease_start,lease_end,contracted_rent,payment_status\n"
        "1,2024-01-01,2026-03-01,1000,current\n"
        "2,2024-01-01,2026-03-15,1000,current\n"
        "3,2024-01-01,2026-04-01,1000,current\n"
        "4,2024-01-01,2027-01-01,1000,current\n"
    ).encode("utf-8")
    summary = parse_csv(csv_bytes)
    assert summary.expiration_flag is True
    assert summary.expiration_flag_detail["expiring_count"] == 3
    assert summary.expiration_flag_detail["total_occupied"] == 4


def test_expiration_concentration_flag_not_triggered_when_spread_out():
    # 20 units (ZONIQ's actual target range, Section 02), lease ends staggered ~30
    # days apart across nearly two years — at most 2-3 units ever share a 60-day
    # window (10-15%), comfortably under the 25% threshold. With only 4 total units
    # (as in the "triggers" test above), a single lease alone is already 25% of the
    # building — that's a correct reflection of the rule at small unit counts, not
    # something to work around here.
    from datetime import date, timedelta

    rows = ["unit_id,lease_start,lease_end,contracted_rent,payment_status"]
    start = date(2024, 1, 1)
    for i in range(20):
        lease_end = start + timedelta(days=30 * i)
        rows.append(f"{i+1},2023-01-01,{lease_end.isoformat()},1000,current")
    csv_bytes = "\n".join(rows).encode("utf-8")

    summary = parse_csv(csv_bytes)
    assert summary.expiration_flag is False
    assert summary.expiration_flag_detail is None


def test_parse_excel(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["unit_id", "lease_start", "lease_end", "contracted_rent", "payment_status"])
    sheet.append(["201", "2025-01-01", "2026-01-01", 1200, "current"])
    sheet.append(["202", "2025-01-01", "2026-01-01", 0, "vacant"])
    buf = io.BytesIO()
    workbook.save(buf)

    summary = parse_excel(buf.getvalue())
    assert len(summary.units) == 2
    assert summary.gross_rent == 1200
    assert summary.vacancy_rate == 0.5


def test_parse_excel_missing_columns_raises():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["unit_id", "rent"])
    sheet.append(["1", 1000])
    buf = io.BytesIO()
    workbook.save(buf)

    with pytest.raises(ValueError, match="missing required columns"):
        parse_excel(buf.getvalue())


def test_parse_pdf():
    doc = fitz.open()
    page = doc.new_page()
    text = (
        "unit_id  lease_start  lease_end  contracted_rent  payment_status\n"
        "301  2025-01-01  2026-01-01  1350  current\n"
        "302  2025-01-01  2026-01-01  0  vacant\n"
    )
    page.insert_text((36, 72), text, fontsize=10)
    pdf_bytes = doc.tobytes()
    doc.close()

    summary = parse_pdf(pdf_bytes)
    assert len(summary.units) == 2
    assert summary.gross_rent == 1350
    assert summary.vacancy_rate == 0.5


def test_parse_rent_roll_dispatches_by_extension():
    summary = parse_rent_roll(CSV_SAMPLE, "rent_roll.csv")
    assert len(summary.units) == 4


def test_parse_rent_roll_rejects_unsupported_extension():
    with pytest.raises(ValueError, match="Unsupported rent roll file type"):
        parse_rent_roll(b"whatever", "rent_roll.docx")
