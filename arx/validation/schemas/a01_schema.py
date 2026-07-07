"""A-01 Deal Screener output schema — Section 87."""
from typing import Literal

from pydantic import BaseModel, Field


class A01Output(BaseModel):
    deal_id: str
    deal_type_detected: Literal["acquisition", "land", "development"]
    go_no_go: Literal["go", "no_go", "conditional_go"]
    preliminary_cap_rate: float | None = None
    preliminary_roc: float | None = None
    in_target_range: bool
    missing_fields: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=50)
    routing_recommendation: Literal["route_to_a02", "route_to_a10", "no_go_end"]
    confidence_score: Literal["high", "medium", "low"]
    document_extraction_required: bool
