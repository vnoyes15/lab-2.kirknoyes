"""A-05 LOI Drafting Agent output schema — Section 87, Section 18 (WA law)."""
from pydantic import BaseModel, Field


class A05Output(BaseModel):
    loi_text: str = Field(min_length=500)
    # Section 87: "Mandatory. Must be present. Hardcoded validation check: null or
    # empty = unrecoverable error." min_length=1 here is schema-level defense; the
    # agent adds an explicit non-blank check too (arx/agents/a05_loi_drafting.py) —
    # deliberate belt-and-suspenders given WA1's "never omitted" framing.
    attorney_review_warning: str = Field(min_length=1)
    # Section 87 / WA1: must be true; false is unrecoverable, not just a warning.
    escrow_reference_present: bool
    jurisdiction_flags: list[str] = Field(default_factory=list)
    # Set by the write layer after storage to the document vault — never the model.
    document_vault_path: str | None = None
