"""LLM extraction for conference and career events (B5)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from assistant.config import Settings
from assistant.domain.events import AttendanceMode, CareerEventType
from assistant.extraction.base import MessageView
from assistant.extraction.events.base import (
    ExtractedCareerEvent,
    ExtractedConferenceEvent,
    ExtractedEvents,
)
from assistant.extraction.events.validation import validate_career_events, validate_conference_events
from assistant.extraction.llm_cost import LlmUsage, LlmUsageTotals, format_llm_cost_usd
from assistant.extraction.llm_fallback import message_body_for_llm
from assistant.extraction.money import parse_money_token
from assistant.extraction.validation import ExtractionRejected

logger = logging.getLogger(__name__)

TOOL_NAME = "extract_event_records"

AttendanceModeLiteral = Literal["ONLINE", "IN_PERSON", "HYBRID", "UNKNOWN"]
CareerEventTypeLiteral = Literal[
    "JOB_POSTING",
    "RECRUITER_OUTREACH",
    "INTERVIEW_INVITE",
    "APPLICATION_UPDATE",
    "OTHER",
]


class LlmConferenceEvent(BaseModel):
    name: str
    starts_on: str | None = Field(
        default=None, description="ISO date YYYY-MM-DD when explicitly stated"
    )
    ends_on: str | None = Field(default=None, description="ISO date YYYY-MM-DD for multi-day events")
    location: str | None = None
    attendance_mode: AttendanceModeLiteral | None = None
    price_raw: str | None = Field(
        default=None,
        description="Exact price substring from the email when stated, e.g. 'Free' or '49 EUR'",
    )
    currency: str | None = Field(default=None, description="ISO 4217 when price is stated")
    registration_deadline: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    cfp_deadline: str | None = Field(default=None, description="ISO date YYYY-MM-DD for CFP")
    evidence_quote: str = Field(
        description="Exact verbatim substring from the email body supporting this event"
    )


class LlmCareerEvent(BaseModel):
    event_type: CareerEventTypeLiteral
    company: str
    position: str | None = None
    event_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    deadline: str | None = Field(default=None, description="ISO date YYYY-MM-DD application deadline")
    next_step: str | None = Field(default=None, description="Suggested next action when stated")
    evidence_quote: str = Field(
        description="Exact verbatim substring from the email body supporting this event"
    )


class LlmEventExtractionPayload(BaseModel):
    conference_events: list[LlmConferenceEvent] = Field(default_factory=list)
    career_events: list[LlmCareerEvent] = Field(default_factory=list)


SYSTEM_PROMPT = """You extract structured IT conference/meetup events and career-related events from personal emails.

Rules:
- Return empty lists if the email has no specific conference, meetup, job posting, or career opportunity.
- Generic newsletters without concrete event details → return empty lists.
- Never invent names, dates, locations, companies, or deadlines.
- evidence_quote MUST be copied exactly from the Email body section below (character-for-character, same line breaks).
- Copy text exactly as it appears — do not replace line breaks or "fix" spelling.
- If price_raw is set, it MUST appear inside evidence_quote exactly as written.
- If you cannot copy a contiguous quote that includes the price, leave price_raw null.
- For multi-email campaigns about one conference (e.g. DEV.BG All In One 2026), prefer ONE conference record for the main event, not one record per marketing paragraph.
- Optional: separate records for distinct scheduled talks/meetups with their own date/time/location.
- Leave dates null when not explicitly stated — do not guess.
- Conference events: meetups, conferences, workshops, hackathons, CFP announcements.
- Career events: job postings, recruiter outreach, interview invites, application updates.
"""


def _build_user_prompt(msg: MessageView, body: str) -> str:
    labels = ", ".join(msg.labels) if msg.labels else "(none)"
    return (
        f"From: {msg.sender or 'unknown'}\n"
        f"Subject: {msg.subject or '(no subject)'}\n"
        f"Labels: {labels}\n\n"
        f"Email body:\n---\n{body}\n---"
    )


def _parse_optional_date(value: str | None, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ExtractionRejected(f"invalid {field_name}: {value!r}") from exc


def _parse_optional_price(
    price_raw: str | None, currency: str | None
) -> tuple[int | None, str | None]:
    if not price_raw:
        return None, None
    lowered = price_raw.strip().lower()
    free_markers = ("free", "безплатно", "безплатен", "безплатна")
    if lowered in free_markers or any(marker in lowered for marker in free_markers):
        return 0, currency or "EUR"
    try:
        price_minor, parsed_currency, _ = parse_money_token(price_raw)
    except ValueError as exc:
        raise ExtractionRejected(str(exc)) from exc
    final_currency = (currency or parsed_currency or "EUR").upper()[:3]
    return price_minor, final_currency


def _to_conference_event(item: LlmConferenceEvent) -> ExtractedConferenceEvent:
    attendance: AttendanceMode | None = None
    if item.attendance_mode:
        try:
            attendance = AttendanceMode(item.attendance_mode)
        except ValueError as exc:
            raise ExtractionRejected(f"unknown attendance_mode: {item.attendance_mode!r}") from exc

    price_minor, currency = _parse_optional_price(item.price_raw, item.currency)

    return ExtractedConferenceEvent(
        name=item.name.strip(),
        starts_on=_parse_optional_date(item.starts_on, "starts_on"),
        ends_on=_parse_optional_date(item.ends_on, "ends_on"),
        location=item.location.strip() if item.location else None,
        attendance_mode=attendance,
        price_raw=item.price_raw.strip() if item.price_raw else None,
        price_minor=price_minor,
        currency=currency,
        registration_deadline=_parse_optional_date(item.registration_deadline, "registration_deadline"),
        cfp_deadline=_parse_optional_date(item.cfp_deadline, "cfp_deadline"),
        evidence_quote=item.evidence_quote,
    )


def _to_career_event(item: LlmCareerEvent) -> ExtractedCareerEvent:
    try:
        event_type = CareerEventType(item.event_type)
    except ValueError as exc:
        raise ExtractionRejected(f"unknown event_type: {item.event_type!r}") from exc

    return ExtractedCareerEvent(
        event_type=event_type,
        company=item.company.strip(),
        position=item.position.strip() if item.position else None,
        event_date=_parse_optional_date(item.event_date, "event_date"),
        deadline=_parse_optional_date(item.deadline, "deadline"),
        next_step=item.next_step.strip() if item.next_step else None,
        evidence_quote=item.evidence_quote,
    )


def _parse_tool_payload(data: object) -> LlmEventExtractionPayload:
    if not isinstance(data, dict):
        raise ExtractionRejected("LLM tool input was not an object")
    return LlmEventExtractionPayload.model_validate(data)


async def _call_anthropic(
    msg: MessageView, settings: Settings
) -> tuple[LlmEventExtractionPayload, LlmUsage]:
    from anthropic import AsyncAnthropic

    body = message_body_for_llm(msg)
    if not body:
        raise ExtractionRejected("message has no extractable body text")

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model_haiku,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(msg, body)}],
        tools=[
            {
                "name": TOOL_NAME,
                "description": "Extract conference and career events from the email",
                "input_schema": LlmEventExtractionPayload.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": TOOL_NAME},
    )

    usage = LlmUsage(
        model=settings.anthropic_model_haiku,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    logger.info(
        "Event LLM call message=%s model=%s in=%d out=%d est=%s",
        msg.id,
        usage.model,
        usage.input_tokens,
        usage.output_tokens,
        format_llm_cost_usd(usage.estimated_cost_usd()),
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return _parse_tool_payload(block.input), usage

    raise ExtractionRejected("LLM did not return structured event extraction")


async def extract_events_with_llm(
    msg: MessageView, settings: Settings
) -> tuple[ExtractedEvents, LlmUsageTotals]:
    """Run Haiku event extraction with retries on verbatim validation failure."""
    if not settings.anthropic_api_key:
        raise ExtractionRejected("ANTHROPIC_API_KEY is not configured")

    max_attempts = max(1, settings.citation_max_retries + 1)
    last_error: ExtractionRejected | None = None
    usage_totals = LlmUsageTotals()
    llm_body = message_body_for_llm(msg)
    if not llm_body:
        raise ExtractionRejected("message has no extractable body text")

    for attempt in range(1, max_attempts + 1):
        try:
            payload, usage = await _call_anthropic(msg, settings)
            usage_totals.add(usage)
            if not payload.conference_events and not payload.career_events:
                return ExtractedEvents([], []), usage_totals

            conference = [
                _to_conference_event(item) for item in payload.conference_events
            ]
            career = [_to_career_event(item) for item in payload.career_events]
            conference = validate_conference_events(msg, conference, llm_body=llm_body)
            career = validate_career_events(msg, career, llm_body=llm_body)
            return ExtractedEvents(conference, career), usage_totals
        except ExtractionRejected as exc:
            last_error = exc
            logger.warning(
                "Event LLM attempt %d/%d rejected for message %s: %s",
                attempt,
                max_attempts,
                msg.id,
                exc,
            )

    assert last_error is not None
    raise last_error
