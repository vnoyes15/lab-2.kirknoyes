"""A-02 Underwriting Agent output schema — Section 87.

Some fields here are never produced by the model — annual_debt_service,
dscr_hard_fail, and dscr_warning are computed deterministically in Python
(arx/agents/a02_underwriting_agent.py) and merged into the model's output before this
schema validates the combined result. Section 87 is explicit that annual_debt_service
is "Python-calculated... Not model-estimated"; dscr_hard_fail/dscr_warning are pure
comparisons against that same deterministic dscr, so they get the same treatment.
"""
from typing import Literal

from pydantic import BaseModel, Field


class OperatingExpenses(BaseModel):
    management: float
    maintenance: float
    capex_reserves: float
    insurance: float
    taxes: float
    other: float


class SensitivityScenario(BaseModel):
    cap_rate: float
    dscr: float
    coc: float


class LoadBearingAssumption(BaseModel):
    assumption: str
    why_it_matters: str


class A02Output(BaseModel):
    gross_rent: float
    vacancy_rate: float
    vacancy_amount: float
    operating_expenses: OperatingExpenses
    noi: float

    purchase_price: float
    cap_rate: float

    loan_amount: float
    ltv: float
    interest_rate: float
    amortization_years: int
    annual_debt_service: float  # Python-computed, see module docstring

    dscr: float
    dscr_hard_fail: bool  # Python-computed: dscr < 1.00
    dscr_warning: bool  # Python-computed: dscr < 1.25

    cash_on_cash: float

    # v1.0.0 covers rent sensitivity only (Section 87 also specifies exit-cap
    # sensitivity — noted as a gap for a v1.1 prompt revision, not silently dropped).
    sensitivity_table: dict[str, SensitivityScenario]

    load_bearing_assumptions: list[LoadBearingAssumption] = Field(min_length=3, max_length=3)
    assumption_sources: dict[str, str]
    confidence_score: Literal["high", "medium", "low"]
    no_comp_disclaimer: str | None = None
