"""A-08 Outreach Agent output schema — Section 87, Section 22.

suppression_checked / daily_limit_checked are Python-verified BEFORE the model is
even called (arx/agents/a08_outreach.py never drafts a message to a suppressed
contact or once the daily limit is hit — see that module) and set to True here as a
record of that check having passed, not asked of or trusted from the model.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CHANNEL_MAX_LENGTH = {
    "email": 1500,
    "sms": 500,
    "linkedin": 1500,
    "phone_script": 1500,
}


class A08Output(BaseModel):
    message_text: str = Field(min_length=100)
    channel: Literal["email", "sms", "linkedin", "phone_script"]
    can_spam_placeholder: str | None = None
    suppression_checked: bool
    daily_limit_checked: bool

    @model_validator(mode="after")
    def _validate_channel_length_and_can_spam(self):
        max_len = CHANNEL_MAX_LENGTH[self.channel]
        if len(self.message_text) > max_len:
            raise ValueError(f"message_text is {len(self.message_text)} characters, exceeds the {max_len}-character limit for channel '{self.channel}'")
        if self.channel == "email" and not (self.can_spam_placeholder and self.can_spam_placeholder.strip()):
            raise ValueError("can_spam_placeholder is required for email channel messages (Section 87)")
        if self.suppression_checked is not True:
            raise ValueError("suppression_checked must be true (Section 87 — false is unrecoverable)")
        if self.daily_limit_checked is not True:
            raise ValueError("daily_limit_checked must be true (Section 87 — false is unrecoverable)")
        return self
