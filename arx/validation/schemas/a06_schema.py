"""A-06 Due Diligence Coordinator output schema — Section 87, Section 03.

The checklist *categories* per track are fixed by Section 03's role description
(ACQUISITION TRACK / LAND-DEVELOPMENT TRACK lists) — they are Python-determined in
arx/agents/a06_due_diligence.py, not left to the model to invent, so the checklist is
always complete regardless of what the model does with any individual item's content.
See that module for the category lists.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ChecklistStatus = Literal["not_started", "in_progress", "complete", "flagged"]


class ChecklistItem(BaseModel):
    item_id: str
    category: str
    description: str
    why_it_matters: str
    responsible_party: str
    status: ChecklistStatus
    flag_note: str | None = None
    assigned_user_id: str | None = None

    @model_validator(mode="after")
    def _flag_note_required_when_flagged(self):
        if self.status == "flagged" and (not self.flag_note or len(self.flag_note.strip()) < 20):
            raise ValueError(f"Item '{self.item_id}' is flagged but flag_note is missing or under 20 characters")
        return self


class A06Output(BaseModel):
    dd_track: Literal["acquisition", "land_development"]
    checklist_items: list[ChecklistItem] = Field(min_length=1)
    # Required (non-null) for all WA multifamily deals (WA3) — arx/agents/a06_due_diligence.py
    # enforces this in Python rather than trusting the model to remember.
    wa_rent_compliance_item: ChecklistItem | None = None
    # Computed deterministically in Python from checklist_items' statuses, not
    # reported by the model — see arx/agents/a06_due_diligence.py.
    deal_advancement_blocked: bool
    # Populated by the write layer after deal_tasks rows are created — never the model.
    tasks_created: list[str] = Field(default_factory=list)
