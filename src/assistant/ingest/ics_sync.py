"""Persist expanded ICS calendar events."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.config import Settings
from assistant.crypto import SecretBox
from assistant.db.models import Account, CalendarEvent, IcsSyncState
from assistant.ingest.calendar_ics import (
    ParsedCalendarEvent,
    expand_calendar_events,
    fetch_ics,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpcomingEventSummary:
    summary: str | None
    starts_at: datetime
    all_day: bool


@dataclass(frozen=True)
class IcsSyncResult:
    alias: str
    skipped: bool
    upserted: int
    removed: int
    total_in_window: int
    upcoming: list[UpcomingEventSummary]
    error: str | None = None


def _sync_window(settings: Settings) -> tuple[datetime, datetime]:
    now = datetime.now(tz=UTC)
    start = now - timedelta(days=settings.ics_horizon_days_past)
    end = now + timedelta(days=settings.ics_horizon_days_future)
    return start, end


def _fetch_and_expand(
    *,
    ics_url: str,
    etag: str | None,
    settings: Settings,
) -> tuple[bool, str | None, list[ParsedCalendarEvent]]:
    fetch_result = fetch_ics(ics_url, etag)
    if fetch_result.not_modified or fetch_result.body is None:
        return True, fetch_result.etag, []

    window_start, window_end = _sync_window(settings)
    events = expand_calendar_events(
        fetch_result.body,
        window_start=window_start,
        window_end=window_end,
        timezone_name=settings.journal_timezone,
    )
    return False, fetch_result.etag, events


async def _ensure_ics_sync_state(session: AsyncSession, account_id: int) -> IcsSyncState:
    state = await session.scalar(
        select(IcsSyncState).where(IcsSyncState.account_id == account_id)
    )
    if state is None:
        state = IcsSyncState(account_id=account_id)
        session.add(state)
        await session.flush()
    return state


async def _upsert_events(
    session: AsyncSession, account_id: int, events: list[ParsedCalendarEvent]
) -> int:
    for event in events:
        stmt = (
            insert(CalendarEvent)
            .values(
                account_id=account_id,
                cal_uid=event.cal_uid,
                source_uid=event.source_uid,
                summary=event.summary,
                location=event.location,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                all_day=event.all_day,
                updated_at=func.now(),
            )
            .on_conflict_do_update(
                constraint="uq_calendar_events_account_cal_uid",
                set_={
                    "source_uid": event.source_uid,
                    "summary": event.summary,
                    "location": event.location,
                    "starts_at": event.starts_at,
                    "ends_at": event.ends_at,
                    "all_day": event.all_day,
                    "updated_at": func.now(),
                },
            )
        )
        await session.execute(stmt)
    return len(events)


async def _remove_stale_events(
    session: AsyncSession,
    account_id: int,
    active_uids: set[str],
    window_start: datetime,
    window_end: datetime,
) -> int:
    rows = (
        await session.scalars(
            select(CalendarEvent.cal_uid).where(
                CalendarEvent.account_id == account_id,
                CalendarEvent.starts_at >= window_start,
                CalendarEvent.starts_at <= window_end,
            )
        )
    ).all()
    stale_uids = [uid for uid in rows if uid not in active_uids]
    if not stale_uids:
        return 0

    result = await session.execute(
        delete(CalendarEvent).where(
            CalendarEvent.account_id == account_id,
            CalendarEvent.cal_uid.in_(stale_uids),
        )
    )
    return int(result.rowcount or 0)


async def _load_upcoming(
    session: AsyncSession, account_id: int, limit: int = 5
) -> list[UpcomingEventSummary]:
    now = datetime.now(tz=UTC)
    rows = (
        await session.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.account_id == account_id,
                CalendarEvent.ends_at >= now,
            )
            .order_by(CalendarEvent.starts_at.asc())
            .limit(limit)
        )
    ).all()
    return [
        UpcomingEventSummary(
            summary=row.summary,
            starts_at=row.starts_at,
            all_day=row.all_day,
        )
        for row in rows
    ]


async def sync_all_calendars(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    secret_box: SecretBox,
) -> list[IcsSyncResult]:
    results: list[IcsSyncResult] = []

    async with session_factory() as session:
        accounts = (
            await session.scalars(
                select(Account).where(
                    Account.enabled.is_(True),
                    Account.ics_url_enc.is_not(None),
                )
            )
        ).all()

    window_start, window_end = _sync_window(settings)

    for account in accounts:
        async with session_factory() as session:
            if not account.ics_url_enc:
                continue

            try:
                ics_url = secret_box.decrypt(account.ics_url_enc)
                sync_state = await _ensure_ics_sync_state(session, account.id)

                skipped, new_etag, events = await asyncio.to_thread(
                    _fetch_and_expand,
                    ics_url=ics_url,
                    etag=sync_state.etag,
                    settings=settings,
                )

                if skipped:
                    upcoming = await _load_upcoming(session, account.id)
                    results.append(
                        IcsSyncResult(
                            alias=account.alias,
                            skipped=True,
                            upserted=0,
                            removed=0,
                            total_in_window=len(upcoming),
                            upcoming=upcoming,
                        )
                    )
                    continue

                active_uids = {event.cal_uid for event in events}
                upserted = await _upsert_events(session, account.id, events)
                removed = await _remove_stale_events(
                    session, account.id, active_uids, window_start, window_end
                )
                sync_state.etag = new_etag
                sync_state.last_synced_at = datetime.now(tz=UTC)
                await session.commit()

                upcoming = await _load_upcoming(session, account.id)
                results.append(
                    IcsSyncResult(
                        alias=account.alias,
                        skipped=False,
                        upserted=upserted,
                        removed=removed,
                        total_in_window=len(events),
                        upcoming=upcoming,
                    )
                )
                logger.info(
                    "ICS sync %s: upserted=%d removed=%d total=%d",
                    account.alias,
                    upserted,
                    removed,
                    len(events),
                )
            except Exception as exc:
                await session.rollback()
                logger.exception("ICS sync failed for %s", account.alias)
                results.append(
                    IcsSyncResult(
                        alias=account.alias,
                        skipped=False,
                        upserted=0,
                        removed=0,
                        total_in_window=0,
                        upcoming=[],
                        error=str(exc),
                    )
                )

    return results
