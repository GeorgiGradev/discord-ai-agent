"""Extractor protocol and extracted record shape."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from assistant.domain.payments import RecordType


@dataclass(frozen=True)
class MessageView:
    id: int
    account_id: int
    gm_msgid: str
    sender: str | None
    subject: str | None
    labels: list[str]
    received_at: datetime | None
    text_body: str | None
    html_body: str | None


@dataclass(frozen=True)
class ExtractedRecord:
    record_type: RecordType
    payee: str
    subscriber_number: str | None
    description: str | None
    amount_minor: int
    currency: str
    amount_raw: str
    due_date: date | None
    payment_status: str | None
    evidence_quote: str
    period_month: str | None = None


class Extractor(Protocol):
    name: str

    def matches(self, msg: MessageView) -> bool: ...

    def extract(self, msg: MessageView) -> list[ExtractedRecord]: ...
