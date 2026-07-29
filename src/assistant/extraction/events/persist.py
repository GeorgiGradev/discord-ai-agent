"""Persist extracted event records with deduplication."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from assistant.db.models import CareerEvent, ConferenceEvent, RawMessage
from assistant.domain.events import (
    normalize_company,
    normalize_event_name,
    normalize_location,
    normalize_position,
)
from assistant.extraction.events.base import ExtractedCareerEvent, ExtractedConferenceEvent


async def persist_conference_events(
    session: AsyncSession,
    *,
    message: RawMessage,
    records: list[ExtractedConferenceEvent],
    extractor_name: str,
) -> list[int]:
    inserted_ids: list[int] = []
    for record in records:
        name_normalized = normalize_event_name(record.name)
        location_normalized = normalize_location(record.location)
        stmt = (
            insert(ConferenceEvent)
            .values(
                raw_message_id=message.id,
                account_id=message.account_id,
                name=record.name,
                name_normalized=name_normalized,
                starts_on=record.starts_on,
                ends_on=record.ends_on,
                location=record.location,
                location_normalized=location_normalized,
                attendance_mode=record.attendance_mode.value if record.attendance_mode else None,
                price_raw=record.price_raw,
                price_minor=record.price_minor,
                currency=record.currency,
                registration_deadline=record.registration_deadline,
                cfp_deadline=record.cfp_deadline,
                evidence_quote=record.evidence_quote,
                extractor_name=extractor_name,
            )
            .on_conflict_do_nothing(constraint="uq_conference_dedup")
            .returning(ConferenceEvent.id)
        )
        result = await session.execute(stmt)
        row_id = result.scalar_one_or_none()
        if row_id is not None:
            inserted_ids.append(int(row_id))
    return inserted_ids


async def persist_career_events(
    session: AsyncSession,
    *,
    message: RawMessage,
    records: list[ExtractedCareerEvent],
    extractor_name: str,
) -> list[int]:
    inserted_ids: list[int] = []
    for record in records:
        company_normalized = normalize_company(record.company)
        position_normalized = normalize_position(record.position)
        stmt = (
            insert(CareerEvent)
            .values(
                raw_message_id=message.id,
                account_id=message.account_id,
                event_type=record.event_type.value,
                company=record.company,
                company_normalized=company_normalized,
                position=record.position,
                position_normalized=position_normalized,
                event_date=record.event_date,
                deadline=record.deadline,
                next_step=record.next_step,
                evidence_quote=record.evidence_quote,
                extractor_name=extractor_name,
            )
            .on_conflict_do_nothing(constraint="uq_career_dedup")
            .returning(CareerEvent.id)
        )
        result = await session.execute(stmt)
        row_id = result.scalar_one_or_none()
        if row_id is not None:
            inserted_ids.append(int(row_id))
    return inserted_ids
