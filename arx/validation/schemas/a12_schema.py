"""A-12 Negotiation Support Agent output schema — Section 87."""
from pydantic import BaseModel, Field, model_validator


class ResponseOption(BaseModel):
    label: str  # "hold_firm" | "partial_concession" | "accept_counter"
    description: str
    return_impact: dict[str, float]
    recommended: bool = False


class A12Output(BaseModel):
    counter_analysis: str = Field(min_length=100)
    # Acquisition: {cap_rate_delta, dscr_delta, coc_delta}. Development:
    # {return_on_cost_delta, spread_delta}.
    deal_impact: dict[str, float]
    response_options: list[ResponseOption] = Field(min_length=3, max_length=3)
    recommendation_rationale: str = Field(min_length=150)
    below_threshold_flag: bool

    @model_validator(mode="after")
    def _exactly_one_recommended(self):
        recommended_count = sum(1 for opt in self.response_options if opt.recommended)
        if recommended_count != 1:
            raise ValueError(f"Exactly one response_option must have recommended=true, got {recommended_count}")
        return self
