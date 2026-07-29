"""Verbatim validation helpers for extracted records."""

from __future__ import annotations

from assistant.extraction.base import ExtractedRecord, MessageView
from assistant.extraction.money import find_verbatim_quote


class ExtractionRejected(ValueError):
    """Raised when extracted data fails verbatim validation."""


def validate_records(msg: MessageView, records: list[ExtractedRecord]) -> list[ExtractedRecord]:
    validated: list[ExtractedRecord] = []
    for record in records:
        try:
            find_verbatim_quote(
                record.evidence_quote,
                text=msg.text_body,
                html=msg.html_body,
            )
        except ValueError as exc:
            raise ExtractionRejected(str(exc)) from exc
        if record.amount_raw not in record.evidence_quote:
            raise ExtractionRejected(
                f"amount {record.amount_raw!r} not in evidence quote {record.evidence_quote!r}"
            )
        validated.append(record)
    return validated
