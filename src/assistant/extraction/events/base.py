"""Extracted event record shapes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from assistant.domain.events import AttendanceMode, CareerEventType


@dataclass(frozen=True)
class ExtractedConferenceEvent:
    name: str
    starts_on: date | None
    ends_on: date | None
    location: str | None
    attendance_mode: AttendanceMode | None
    price_raw: str | None
    price_minor: int | None
    currency: str | None
    registration_deadline: date | None
    cfp_deadline: date | None
    evidence_quote: str


@dataclass(frozen=True)
class ExtractedCareerEvent:
    event_type: CareerEventType
    company: str
    position: str | None
    event_date: date | None
    deadline: date | None
    next_step: str | None
    evidence_quote: str


@dataclass(frozen=True)
class ExtractedEvents:
    conference_events: list[ExtractedConferenceEvent]
    career_events: list[ExtractedCareerEvent]
