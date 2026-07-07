"""A-07 Deal Memo Writer output schema — Section 87."""
from typing import Literal

from pydantic import BaseModel, Field


class MemoSections(BaseModel):
    executive_summary: str
    property_overview: str
    market_context: str
    investment_thesis: str
    financial_summary: str
    risk_factors: str = Field(min_length=200)
    deal_structure: str
    next_steps: str


class A07Output(BaseModel):
    memo_track: Literal["acquisition", "development"]
    sections: MemoSections
    # Section 87: "financial_summary_metrics R — Must match active A-02 or A-11
    # snapshot. Discrepancies = unrecoverable error." Distinct from the prose in
    # sections.financial_summary — this is a small structured echo of the key numbers
    # (e.g. {"cap_rate": 0.06, "noi": 300000, "dscr": 1.2} for acquisition) that the
    # agent code can mechanically diff against the snapshot, rather than trying to
    # regex-match numbers out of free text.
    financial_summary_metrics: dict[str, float]
    confidence_disclosure: str | None = None
    audience_version: Literal["internal", "investor_facing"]
    # Set by the write layer after storage to the document vault (Section 87) — never
    # populated by the model itself.
    document_vault_path: str | None = None
