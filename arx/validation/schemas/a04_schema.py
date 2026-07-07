"""A-04 Offer Strategy Agent output schema — Section 87."""
from pydantic import BaseModel, Field


class OfferStrategy(BaseModel):
    purchase_price: float
    financing_structure: str
    seller_rationale: str = Field(min_length=80)
    # Acquisition: {cap_rate, dscr, coc}. Development: {return_on_cost, development_spread}.
    # A single dict rather than a track-specific nested model since one A04Output must
    # support both financial tracks (Section 87 gives both shapes for this one field).
    zoniq_returns: dict[str, float]
    key_risks: list[str] = Field(min_length=2)


class A04Output(BaseModel):
    strategies: list[OfferStrategy] = Field(min_length=3, max_length=3)
    # Required for land/development deals (Section 87); omitted for acquisitions.
    feasibility_contingency_days: int | None = None
