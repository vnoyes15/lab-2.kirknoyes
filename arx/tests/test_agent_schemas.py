import pytest
from pydantic import ValidationError

from arx.validation.schemas.a01_schema import A01Output
from arx.validation.schemas.a02_schema import A02Output
from arx.validation.schemas.a07_schema import A07Output
from arx.validation.schemas.a09_schema import A09Output


def test_a01_schema_valid():
    output = A01Output(
        deal_id="d1",
        deal_type_detected="acquisition",
        go_no_go="go",
        preliminary_cap_rate=0.06,
        preliminary_roc=None,
        in_target_range=True,
        missing_fields=[],
        rationale="x" * 60,
        routing_recommendation="route_to_a02",
        confidence_score="medium",
        document_extraction_required=False,
    )
    assert output.go_no_go == "go"


def test_a01_schema_rejects_short_rationale():
    with pytest.raises(ValidationError):
        A01Output(
            deal_id="d1", deal_type_detected="acquisition", go_no_go="go",
            in_target_range=True, missing_fields=[], rationale="too short",
            routing_recommendation="route_to_a02", confidence_score="medium",
            document_extraction_required=False,
        )


def test_a01_schema_rejects_bad_enum():
    with pytest.raises(ValidationError):
        A01Output(
            deal_id="d1", deal_type_detected="condo", go_no_go="go",
            in_target_range=True, missing_fields=[], rationale="x" * 60,
            routing_recommendation="route_to_a02", confidence_score="medium",
            document_extraction_required=False,
        )


def _valid_a02_kwargs() -> dict:
    scenario = {"cap_rate": 0.06, "dscr": 1.2, "coc": 0.04}
    return dict(
        gross_rent=500_000, vacancy_rate=0.07, vacancy_amount=35_000,
        operating_expenses={"management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
                             "insurance": 25_000, "taxes": 40_000, "other": 10_000},
        noi=300_000, purchase_price=5_000_000, cap_rate=0.06,
        loan_amount=3_750_000, ltv=0.75, interest_rate=0.065, amortization_years=30,
        annual_debt_service=250_000, dscr=1.2, dscr_hard_fail=False, dscr_warning=False,
        cash_on_cash=0.04,
        sensitivity_table={
            "rent_-10pct": scenario, "rent_-5pct": scenario, "base": scenario,
            "rent_+5pct": scenario, "rent_+10pct": scenario,
        },
        load_bearing_assumptions=[
            {"assumption": "vacancy", "why_it_matters": "x"},
            {"assumption": "exit cap", "why_it_matters": "x"},
            {"assumption": "interest rate", "why_it_matters": "x"},
        ],
        assumption_sources={"gross_rent": "user_provided"},
        confidence_score="high",
        no_comp_disclaimer=None,
    )


def test_a02_schema_valid():
    output = A02Output(**_valid_a02_kwargs())
    assert output.dscr_hard_fail is False


def test_a02_schema_requires_exactly_three_load_bearing_assumptions():
    kwargs = _valid_a02_kwargs()
    kwargs["load_bearing_assumptions"] = kwargs["load_bearing_assumptions"][:2]
    with pytest.raises(ValidationError):
        A02Output(**kwargs)


def test_a07_schema_valid():
    output = A07Output(
        memo_track="acquisition",
        sections={
            "executive_summary": "x", "property_overview": "x", "market_context": "x",
            "investment_thesis": "x", "financial_summary": "x",
            "risk_factors": "x" * 200, "deal_structure": "x", "next_steps": "x",
        },
        financial_summary_metrics={"cap_rate": 0.06},
        confidence_disclosure=None,
        audience_version="internal",
    )
    assert output.audience_version == "internal"


def test_a07_schema_rejects_short_risk_factors():
    with pytest.raises(ValidationError):
        A07Output(
            memo_track="acquisition",
            sections={
                "executive_summary": "x", "property_overview": "x", "market_context": "x",
                "investment_thesis": "x", "financial_summary": "x",
                "risk_factors": "too short", "deal_structure": "x", "next_steps": "x",
            },
            financial_summary_metrics={"cap_rate": 0.06},
            audience_version="internal",
        )


def test_a09_schema_valid():
    output = A09Output(
        document_type_detected="rent_roll",
        extraction_completeness="complete",
        extracted_fields={
            "gross_rent": {"value": 500_000, "source_page": 1, "source_sheet": None, "confidence": "high"},
        },
        missing_required_fields=[],
        conflicts_detected=[],
        appraisal_cross_reference=None,
        financials_db_mapping=[
            {"input_field": "gross_rent", "input_value": 500_000, "extraction_source": "a09_extracted"},
        ],
    )
    assert output.extraction_completeness == "complete"


def test_a09_schema_rejects_bad_document_type():
    with pytest.raises(ValidationError):
        A09Output(
            document_type_detected="invoice",
            extraction_completeness="complete",
            extracted_fields={}, missing_required_fields=[], conflicts_detected=[],
            financials_db_mapping=[],
        )
