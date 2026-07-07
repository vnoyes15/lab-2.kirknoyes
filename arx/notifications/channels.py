"""Notification delivery channels — Section 06.

NotificationChannel is the swappable-provider seam for delivery, same idea as
arx/agents/model_client.py's ModelClient protocol for the AI provider. InAppChannel is
the only one implemented for real: it persists to the notifications table
(arx/db/queries/notifications.py), which the /api/v1/notifications endpoints read —
that's a complete, working delivery path with no external dependency.

EmailChannel and SMSChannel are deliberately unimplemented, not silently absent: this
environment has no SendGrid/Twilio credentials (same gap already documented for A-08's
actual send delivery and the deferred conversational interface — see README's Phase 4
scope-boundary section). Calling them raises NotImplementedError with a clear message
rather than pretending to send something. Wiring a real provider here later doesn't
change any caller — they only ever depend on the NotificationChannel protocol.
"""
from typing import Protocol

import psycopg

from arx.agents.notification_rules import NotificationSpec
from arx.db.queries.notifications import create_notification


class NotificationChannel(Protocol):
    def send(
        self, conn: psycopg.Connection, *, org_id: str, spec: NotificationSpec,
        deal_id: str | None = None, recipient_user_id: str | None = None,
    ) -> str:
        ...


class InAppChannel:
    """Writes to the notifications table. Always available — no external provider."""

    def send(
        self, conn: psycopg.Connection, *, org_id: str, spec: NotificationSpec,
        deal_id: str | None = None, recipient_user_id: str | None = None,
    ) -> str:
        return create_notification(
            conn, org_id=org_id, spec=spec, deal_id=deal_id, recipient_user_id=recipient_user_id,
        )


class EmailChannel:
    """Deferred — no email provider configured in this environment (Phase 4 scope
    boundary, same as the rest of this module's docstring)."""

    def send(self, conn: psycopg.Connection, **kwargs) -> str:
        raise NotImplementedError(
            "EmailChannel is not wired to a provider yet — no SendGrid/SES credentials "
            "configured. Use InAppChannel, or wire a real provider before enabling this."
        )


class SMSChannel:
    """Deferred — no SMS provider configured in this environment."""

    def send(self, conn: psycopg.Connection, **kwargs) -> str:
        raise NotImplementedError(
            "SMSChannel is not wired to a provider yet — no Twilio credentials "
            "configured. Use InAppChannel, or wire a real provider before enabling this."
        )
