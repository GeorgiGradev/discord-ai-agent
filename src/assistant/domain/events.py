"""Conference and career event domain types."""

from __future__ import annotations

import enum
import re


class AttendanceMode(str, enum.Enum):
    ONLINE = "ONLINE"
    IN_PERSON = "IN_PERSON"
    HYBRID = "HYBRID"
    UNKNOWN = "UNKNOWN"


class CareerEventType(str, enum.Enum):
    JOB_POSTING = "JOB_POSTING"
    RECRUITER_OUTREACH = "RECRUITER_OUTREACH"
    INTERVIEW_INVITE = "INTERVIEW_INVITE"
    APPLICATION_UPDATE = "APPLICATION_UPDATE"
    OTHER = "OTHER"


def normalize_event_name(value: str) -> str:
    cleaned = value.strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def normalize_location(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def normalize_company(value: str) -> str:
    return normalize_event_name(value)


def normalize_position(value: str | None) -> str:
    if not value:
        return ""
    return normalize_event_name(value)
