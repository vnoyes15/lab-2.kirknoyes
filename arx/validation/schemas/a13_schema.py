"""A-13 Capital Raise Intelligence Agent output schema — Section 87."""
from pydantic import BaseModel, Field


class InvestorMatch(BaseModel):
    lp_id: str
    name: str
    fit_score: int = Field(ge=0, le=100)
    check_size_fit: str
    return_expectations_fit: str
    asset_type_fit: str
    geographic_fit: str
    relationship_status: str
    recommended_approach: str


class TrackRecordSummary(BaseModel):
    deals_closed: int = Field(ge=0)
    total_equity_deployed: float = Field(ge=0)
    # Section 87: "null if insufficient data. Never fabricate."
    avg_return_vs_projection: float | None = None
    strongest_precedent: str | None = None


class A13Output(BaseModel):
    investor_matches: list[InvestorMatch] = Field(default_factory=list)
    capital_structure_recommendation: str = Field(min_length=150)
    track_record_summary: TrackRecordSummary
    # Required when track_record_summary.deals_closed == 0 (Section 87) — checked in
    # arx/agents/a13_capital_raise.py rather than as a pydantic cross-field validator,
    # so the failure message can be specific about which rule fired.
    no_track_record_disclosure: str | None = None
