"""A-10 Land Acquisition Agent output schema — Section 87, enriched with the
preliminary-feasibility fields Section 03's prose output list describes
(estimated_developable_units, estimated_land_cost_per_unit, entitlement_timeline_estimate_months)
that Section 87's table doesn't spell out as their own rows but the role clearly
calls for ("Preliminary feasibility assessment: estimated developable units,
estimated land cost per unit, entitlement timeline estimate..."). Same treatment as
A-04/A-12's small enrichments beyond their literal Section 87 tables.
"""
from typing import Literal

from pydantic import BaseModel, Field

SITE_RISK_FLAGS = (
    "environmental_concern", "utility_availability_unknown",
    "topographic_constraint", "political_entitlement_risk", "access_limitation",
)

LandSellerArchetype = Literal[
    "family_trust", "municipality", "religious_institution", "estate", "long_hold", "developer_land_banking",
]


class A10Output(BaseModel):
    feasibility_recommendation: Literal["pursue", "conditional_pursue", "pass"]
    entitlement_path: Literal["by_right", "discretionary_approval_required", "rezoning_required", "unknown"]
    site_risk_flags: list[str] = Field(default_factory=list)
    seller_archetype: LandSellerArchetype
    routing_recommendation: Literal["route_to_a11", "route_to_a03_then_a11", "pass_end"]
    confidence_score: Literal["high", "medium", "low"]

    estimated_developable_units: int | None = None
    estimated_land_cost_per_unit: float | None = None
    entitlement_timeline_estimate_months: int | None = None
    land_cost_benchmark_comparison: str | None = None
