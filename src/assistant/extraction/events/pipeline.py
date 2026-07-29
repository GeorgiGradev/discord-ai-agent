"""Event extraction pipeline for labeled emails."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.config import Settings
from assistant.db.models import RawMessage
from assistant.extraction.base import MessageView
from assistant.extraction.events.llm_extract import extract_events_with_llm
from assistant.extraction.events.persist import persist_career_events, persist_conference_events
from assistant.extraction.llm_cost import LlmUsageTotals
from assistant.extraction.validation import ExtractionRejected

logger = logging.getLogger(__name__)

EVENT_LABELS = frozenset({"devbg", "udemy", "localagi"})
EVENT_SENDER_HINTS = ("@dev.bg", "@udemy.com", "email.udemy.com")


def _event_candidate_sql_filter():
    sender_match = or_(
        RawMessage.sender.ilike("%@dev.bg%"),
        RawMessage.sender.ilike("%@udemy.com%"),
        RawMessage.sender.ilike("%email.udemy.com%"),
    )
    label_match = text(
        "EXISTS (SELECT 1 FROM jsonb_array_elements_text(labels) AS lbl "
        "WHERE lower(lbl) = ANY(ARRAY['devbg','udemy','localagi']))"
    )
    return or_(sender_match, label_match)


@dataclass(frozen=True)
class FailedEventExtraction:
    message_id: int
    subject: str | None
    sender: str | None
    reason: str


@dataclass(frozen=True)
class EventExtractionResult:
    processed: int
    extracted: int
    skipped: int
    no_match: int
    failed: int
    inserted_conference: int
    inserted_career: int
    new_conference_ids: list[int]
    new_career_ids: list[int]
    failures: list[FailedEventExtraction] = field(default_factory=list)
    llm_usage: LlmUsageTotals = field(default_factory=LlmUsageTotals)


def _message_view(row: RawMessage) -> MessageView:
    return MessageView(
        id=row.id,
        account_id=row.account_id,
        gm_msgid=row.gm_msgid,
        sender=row.sender,
        subject=row.subject,
        labels=list(row.labels or []),
        received_at=row.received_at,
        text_body=row.text_body,
        html_body=row.html_body,
    )


def _has_event_label(msg: MessageView) -> bool:
    return any(label.lower() in EVENT_LABELS for label in msg.labels)


def _has_event_sender(msg: MessageView) -> bool:
    sender = (msg.sender or "").lower()
    return any(hint in sender for hint in EVENT_SENDER_HINTS)


def is_event_candidate(msg: MessageView) -> bool:
    return _has_event_label(msg) or _has_event_sender(msg)


async def process_pending_event_messages(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings | None = None,
    *,
    batch_size: int | None = None,
) -> EventExtractionResult:
    effective_batch = batch_size
    if effective_batch is None and settings is not None:
        effective_batch = settings.event_extraction_batch_size
    if effective_batch is None:
        effective_batch = 5

    processed = extracted = skipped = no_match = failed = 0
    inserted_conference = inserted_career = 0
    new_conference_ids: list[int] = []
    new_career_ids: list[int] = []
    failures: list[FailedEventExtraction] = []
    llm_usage_total = LlmUsageTotals()

    async with session_factory() as session:
        pending = (
            await session.scalars(
                select(RawMessage)
                .where(
                    RawMessage.event_extraction_status == "pending",
                    _event_candidate_sql_filter(),
                )
                .order_by(RawMessage.received_at.desc().nullslast(), RawMessage.id.desc())
                .limit(effective_batch)
            )
        ).all()

    for row in pending:
        msg = _message_view(row)
        if not is_event_candidate(msg):
            async with session_factory() as session:
                db_row = await session.get(RawMessage, row.id)
                if db_row is not None:
                    db_row.event_extraction_status = "skipped"
                    await session.commit()
            skipped += 1
            continue

        if settings is None or not settings.llm_extraction_enabled or not settings.anthropic_api_key:
            async with session_factory() as session:
                db_row = await session.get(RawMessage, row.id)
                if db_row is not None:
                    db_row.event_extraction_status = "no_match"
                    await session.commit()
            no_match += 1
            continue

        processed += 1
        try:
            events, llm_usage = await extract_events_with_llm(msg, settings)
            llm_usage_total.merge(llm_usage)
        except ExtractionRejected as exc:
            async with session_factory() as session:
                db_row = await session.get(RawMessage, row.id)
                if db_row is not None:
                    db_row.event_extraction_status = "failed"
                    await session.commit()
            failed += 1
            failures.append(
                FailedEventExtraction(
                    message_id=row.id,
                    subject=row.subject,
                    sender=row.sender,
                    reason=str(exc),
                )
            )
            continue
        except Exception:
            async with session_factory() as session:
                db_row = await session.get(RawMessage, row.id)
                if db_row is not None:
                    db_row.event_extraction_status = "failed"
                    await session.commit()
            failed += 1
            failures.append(
                FailedEventExtraction(
                    message_id=row.id,
                    subject=row.subject,
                    sender=row.sender,
                    reason="unexpected extraction error",
                )
            )
            logger.exception("Event extraction failed for message %s", row.id)
            continue

        if not events.conference_events and not events.career_events:
            async with session_factory() as session:
                db_row = await session.get(RawMessage, row.id)
                if db_row is not None:
                    db_row.event_extraction_status = "no_match"
                    await session.commit()
            no_match += 1
            continue

        async with session_factory() as session:
            db_row = await session.get(RawMessage, row.id)
            if db_row is None:
                continue
            conf_ids = await persist_conference_events(
                session,
                message=db_row,
                records=events.conference_events,
                extractor_name="llm_haiku",
            )
            career_ids = await persist_career_events(
                session,
                message=db_row,
                records=events.career_events,
                extractor_name="llm_haiku",
            )
            db_row.event_extraction_status = "extracted"
            await session.commit()
            extracted += 1
            inserted_conference += len(conf_ids)
            inserted_career += len(career_ids)
            new_conference_ids.extend(conf_ids)
            new_career_ids.extend(career_ids)

    return EventExtractionResult(
        processed=processed,
        extracted=extracted,
        skipped=skipped,
        no_match=no_match,
        failed=failed,
        inserted_conference=inserted_conference,
        inserted_career=inserted_career,
        new_conference_ids=new_conference_ids,
        new_career_ids=new_career_ids,
        failures=failures,
        llm_usage=llm_usage_total,
    )
