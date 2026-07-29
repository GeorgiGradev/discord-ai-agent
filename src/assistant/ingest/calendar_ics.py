"""Fetch and parse Google Calendar ICS feeds."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import icalendar
from recurring_ical_events import of as events_of

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IcsFetchResult:
    not_modified: bool
    etag: str | None
    body: bytes | None


@dataclass(frozen=True)
class ParsedCalendarEvent:
    cal_uid: str
    source_uid: str
    summary: str | None
    location: str | None
    starts_at: datetime
    ends_at: datetime
    all_day: bool


def fetch_ics(url: str, etag: str | None) -> IcsFetchResult:
    headers = {"User-Agent": "Anabella-Calendar-Sync/0.1"}
    if etag:
        headers["If-None-Match"] = etag

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url, headers=headers)

    if response.status_code == 304:
        return IcsFetchResult(not_modified=True, etag=etag, body=None)

    response.raise_for_status()
    return IcsFetchResult(
        not_modified=False,
        etag=response.headers.get("ETag") or etag,
        body=response.content,
    )


def _as_utc(value: date | datetime, tz: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=tz).astimezone(UTC)
        return value.astimezone(UTC)
    return datetime.combine(value, datetime.min.time(), tzinfo=tz).astimezone(UTC)


def _event_end(start: date | datetime, end: date | datetime | None, tz: ZoneInfo) -> datetime:
    if end is None:
        if isinstance(start, datetime):
            return _as_utc(start, tz) + timedelta(hours=1)
        end_date = start + timedelta(days=1)
        return datetime.combine(end_date, datetime.min.time(), tzinfo=tz).astimezone(UTC)

    if isinstance(start, date) and not isinstance(start, datetime):
        if isinstance(end, datetime):
            end = end.date()
        if end <= start:
            end = start + timedelta(days=1)
        return datetime.combine(end, datetime.min.time(), tzinfo=tz).astimezone(UTC)

    return _as_utc(end, tz)


def _occurrence_uid(source_uid: str, start: datetime) -> str:
    raw = f"{source_uid}|{start.astimezone(UTC).isoformat()}"
    if len(raw) <= 255:
        return raw
    return hashlib.sha256(raw.encode()).hexdigest()


def _decode_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def expand_calendar_events(
    ics_body: bytes,
    *,
    window_start: datetime,
    window_end: datetime,
    timezone_name: str,
) -> list[ParsedCalendarEvent]:
    calendar = icalendar.Calendar.from_ical(ics_body)
    tz = ZoneInfo(timezone_name)
    local_start = window_start.astimezone(tz)
    local_end = window_end.astimezone(tz)

    parsed: list[ParsedCalendarEvent] = []
    for item in events_of(calendar).between(local_start, local_end):
        source_uid = _decode_text(item.get("UID"))
        if not source_uid:
            continue

        start_raw = item.get("DTSTART").dt
        end_raw = item.get("DTEND")
        end_value = end_raw.dt if end_raw is not None else None
        starts_at = _as_utc(start_raw, tz)
        ends_at = _event_end(start_raw, end_value, tz)
        all_day = isinstance(start_raw, date) and not isinstance(start_raw, datetime)

        parsed.append(
            ParsedCalendarEvent(
                cal_uid=_occurrence_uid(source_uid, starts_at),
                source_uid=source_uid,
                summary=_decode_text(item.get("SUMMARY")),
                location=_decode_text(item.get("LOCATION")),
                starts_at=starts_at,
                ends_at=ends_at,
                all_day=all_day,
            )
        )

    logger.info("Expanded %d calendar occurrences in sync window", len(parsed))
    return parsed
