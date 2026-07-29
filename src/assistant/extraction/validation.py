"""Verbatim validation helpers for extracted records."""

from __future__ import annotations

from assistant.extraction.base import ExtractedRecord, MessageView
from assistant.extraction.money import find_verbatim_quote


def validate_records(msg: MessageView, records: list[ExtractedRecord]) -> list[ExtractedRecord]:
    validated: list[ExtractedRecord] = []
    for record in records:
        find_verbatim_quote(
            record.evidence_quote,
            text=msg.text_body,
            html=msg.html_body,
        )
        if record.amount_raw not in record.evidence_quote:
            raise ValueError(
                f"amount {record.amount_raw!r} not in evidence quote {record.evidence_quote!r}"
            )
        validated.append(record)
    return validated
