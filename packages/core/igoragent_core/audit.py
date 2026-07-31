from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, Field


class AuditOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    PENDING_APPROVAL = "pending_approval"
    EXECUTED = "executed"
    FAILED = "failed"


class AuditEvent(BaseModel):
    event_id: str
    occurred_at: datetime
    actor_id: int | None = None
    action: str
    outcome: AuditOutcome
    detail: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str = ""
    event_hash: str = ""

    def seal(self) -> "AuditEvent":
        payload = self.model_dump(mode="json", exclude={"event_hash"})
        self.event_hash = sha256(repr(sorted(payload.items())).encode()).hexdigest()
        return self


class AuditTrail:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> AuditEvent:
        event.previous_hash = self._events[-1].event_hash if self._events else ""
        self._events.append(event.seal())
        return event

    def list(self) -> list[AuditEvent]:
        return list(self._events)
