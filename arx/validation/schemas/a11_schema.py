"""A-11 Development Pro Forma Agent output schema — Section 87.

confidence_score is a compound object for this agent specifically: Section 87 says
"Includes entitlement_confidence and construction_cost_confidence as sub-fields" —
every other agent's confidence_score is a plain "high"|"medium"|"low" string, but
A-11's own row calls out these two sub-fields explicitly, so it's structured here as
an object rather than a bare string.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ConfidenceLevel = Literal["high", "medium", "low"]
RISK_FLAG_CATEGORIES = ("entitlement", "construction_cost", "absorption", "financing")


class CostBreakdown(BaseModel):
    land_cost: float
    hard_costs: float
    soft_costs: float
    financing_costs: float
    contingency: float


class DrawPeriod(BaseModel):
    period: str  # e.g. "Q1", "Q2", ...
    draw_amount: float
    cumulative_drawn: float


class DevelopmentSensitivityScenario(BaseModel):
    return_on_cost: float


class A11Confidence(BaseModel):
    overall: ConfidenceLevel
    entitlement_confidence: ConfidenceLevel
    construction_cost_confidence: ConfidenceLevel


class A11Output(BaseModel):
    total_project_cost: float
    cost_breakdown: CostBreakdown
    stabilized_noi: float
    return_on_cost: float
    exit_cap_rate: float
    development_spread: float
    value_destructive: bool

    cash_flows: list[float]
    irr: float

    construction_draw_schedule: list[DrawPeriod]

    # DV5 covers two independent sensitivity axes (Section 87: "cost overrun
    # +5%/10%/15% and absorption delay 3mo/6mo scenarios") — modeled as two separate
    # scenario dicts rather than one combined table, since they aren't points on a
    # single ordered axis the way A-02's rent +/-% sensitivity is.
    cost_overrun_sensitivity: dict[str, DevelopmentSensitivityScenario]
    absorption_delay_sensitivity: dict[str, DevelopmentSensitivityScenario]

    # At least one per category (Section 87): entitlement, construction_cost,
    # absorption, financing. Each flag is "<category>:<detail>" so the category
    # coverage is actually checkable (see _covers_all_risk_categories below) rather
    # than just counting items, which wouldn't catch 4 flags all from one category.
    risk_flags: list[str] = Field(min_length=len(RISK_FLAG_CATEGORIES))

    confidence_score: A11Confidence

    @model_validator(mode="after")
    def _covers_all_risk_categories(self):
        present = {flag.split(":", 1)[0] for flag in self.risk_flags}
        missing = [c for c in RISK_FLAG_CATEGORIES if c not in present]
        if missing:
            raise ValueError(
                f"risk_flags must include at least one flag per category {RISK_FLAG_CATEGORIES}; "
                f"missing: {missing}. Each flag must be formatted '<category>:<detail>'."
            )
        return self
