"""Memory domain types for vector indexing (C1)."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class MemoryKind(str, enum.Enum):
    PAYMENT = "payment"
    EVENT_CONFERENCE = "event_conference"
    EVENT_CAREER = "event_career"
    CALENDAR = "calendar"


@dataclass(frozen=True)
class MemoryChunk:
    kind: MemoryKind
    source_id: str
    content: str
    metadata: dict
    content_hash: str


def payment_source_id(record_id: int) -> str:
    return f"p:{record_id}"
