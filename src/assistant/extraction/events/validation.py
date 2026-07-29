"""Verbatim validation for extracted events."""

from __future__ import annotations

import logging

from assistant.extraction.base import MessageView
from assistant.extraction.citations import find_quote_in_llm_body
from assistant.extraction.events.base import ExtractedCareerEvent, ExtractedConferenceEvent
from assistant.extraction.validation import ExtractionRejected

logger = logging.getLogger(__name__)


def _strip_unquoted_price(
    record: ExtractedConferenceEvent,
    llm_body: str,
) -> ExtractedConferenceEvent:
    if not record.price_raw or record.price_raw in record.evidence_quote:
        return record
    try:
        find_quote_in_llm_body(record.price_raw, llm_body)
    except ValueError:
        return record
    logger.info(
        "Dropped price %r from event %r — not inside evidence quote",
        record.price_raw,
        record.name,
    )
    return ExtractedConferenceEvent(
        name=record.name,
        starts_on=record.starts_on,
        ends_on=record.ends_on,
        location=record.location,
        attendance_mode=record.attendance_mode,
        price_raw=None,
        price_minor=None,
        currency=None,
        registration_deadline=record.registration_deadline,
        cfp_deadline=record.cfp_deadline,
        evidence_quote=record.evidence_quote,
    )


def validate_conference_events(
    msg: MessageView,
    records: list[ExtractedConferenceEvent],
    *,
    llm_body: str,
) -> list[ExtractedConferenceEvent]:
    del msg  # validation uses llm_body, the single source of truth for LLM extraction
    validated: list[ExtractedConferenceEvent] = []
    for record in records:
        try:
            find_quote_in_llm_body(record.evidence_quote, llm_body)
        except ValueError as exc:
            raise ExtractionRejected(str(exc)) from exc
        record = _strip_unquoted_price(record, llm_body)
        validated.append(record)
    return validated


def validate_career_events(
    msg: MessageView,
    records: list[ExtractedCareerEvent],
    *,
    llm_body: str,
) -> list[ExtractedCareerEvent]:
    del msg
    validated: list[ExtractedCareerEvent] = []
    for record in records:
        try:
            find_quote_in_llm_body(record.evidence_quote, llm_body)
        except ValueError as exc:
            raise ExtractionRejected(str(exc)) from exc
        validated.append(record)
    return validated
