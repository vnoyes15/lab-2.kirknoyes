"""A-03 Motivated Seller Profiler output schema — Section 87."""
from typing import Literal

from pydantic import BaseModel, Field

SellerArchetype = Literal[
    "long_hold", "distressed", "estate", "absentee", "institutional",
    "family_trust", "municipality", "religious_institution", "developer_land_banking",
]


class A03Output(BaseModel):
    seller_archetype: SellerArchetype
    distress_indicators: list[str] = Field(default_factory=list)
    motivated_seller_score: int = Field(ge=0, le=100)
    outreach_approach: str = Field(min_length=100)
    topics_to_avoid: list[str] = Field(min_length=1)
    confidence_score: Literal["high", "medium", "low"]
