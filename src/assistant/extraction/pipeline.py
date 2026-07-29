"""Extraction cascade for pending raw messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.db.models import RawMessage
from assistant.extraction.base import ExtractedRecord, MessageView
from assistant.extraction.jsonld import extract_jsonld
from assistant.extraction.persist import persist_extracted_records
from assistant.extraction.registry import get_template_extractors

logger = logging.getLogger(__name__)

PAYMENT_LABEL = "payment"
BATCH_SIZE = 50

PAYMENT_SENDER_HINTS = (
    "bitovismetki@ubb.bg",
    "invoice+statements@mail.anthropic.com",
    "@dskbank.bg",
    "@ubb.bg",
)


@dataclass(frozen=True)
class ExtractionResult:
    processed: int
    extracted: int
    skipped: int
    no_match: int
    failed: int
    inserted_records: int
    new_record_ids: list[int]


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


def _has_payment_label(msg: MessageView) -> bool:
    return any(label.lower() == PAYMENT_LABEL for label in msg.labels)


def _is_payment_candidate(msg: MessageView) -> bool:
    if _has_payment_label(msg):
        return True
    sender = (msg.sender or "").lower()
    if any(hint in sender for hint in PAYMENT_SENDER_HINTS):
        return True
    return any(extractor.matches(msg) for extractor in get_template_extractors())


def _run_cascade(msg: MessageView) -> tuple[list[ExtractedRecord], str | None, bool]:
    """Returns records, extractor name, and whether a template matched but failed."""
    jsonld_records = extract_jsonld(msg)
    if jsonld_records:
        return jsonld_records, "jsonld", False

    for extractor in get_template_extractors():
        if not extractor.matches(msg):
            continue
        try:
            records = extractor.extract(msg)
        except Exception:
            logger.exception("Extractor %s failed for message %s", extractor.name, msg.id)
            raise
        if records:
            return records, extractor.name, False
        logger.warning(
            "Extractor %s matched message %s but returned no records",
            extractor.name,
            msg.id,
        )
        return [], extractor.name, True

    return [], None, False


async def process_pending_messages(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    batch_size: int = BATCH_SIZE,
) -> ExtractionResult:
    processed = extracted = skipped = no_match = failed = 0
    inserted_total = 0
    new_record_ids: list[int] = []

    async with session_factory() as session:
        pending = (
            await session.scalars(
                select(RawMessage)
                .where(RawMessage.extraction_status == "pending")
                .order_by(RawMessage.id.asc())
                .limit(batch_size)
            )
        ).all()

    for row in pending:
        msg = _message_view(row)
        if not _is_payment_candidate(msg):
            async with session_factory() as session:
                db_row = await session.get(RawMessage, row.id)
                if db_row is not None:
                    db_row.extraction_status = "skipped"
                    await session.commit()
            skipped += 1
            continue

        processed += 1
        try:
            records, extractor_name, template_miss = _run_cascade(msg)
        except Exception:
            async with session_factory() as session:
                db_row = await session.get(RawMessage, row.id)
                if db_row is not None:
                    db_row.extraction_status = "failed"
                    await session.commit()
            failed += 1
            continue

        if not records:
            status = "failed" if template_miss else "no_match"
            async with session_factory() as session:
                db_row = await session.get(RawMessage, row.id)
                if db_row is not None:
                    db_row.extraction_status = status
                    await session.commit()
            if template_miss:
                failed += 1
            else:
                no_match += 1
            continue

        async with session_factory() as session:
            db_row = await session.get(RawMessage, row.id)
            if db_row is None:
                continue
            inserted_ids = await persist_extracted_records(
                session,
                message=db_row,
                records=records,
                extractor_name=extractor_name or "unknown",
            )
            db_row.extraction_status = "extracted"
            await session.commit()
            extracted += 1
            inserted_total += len(inserted_ids)
            new_record_ids.extend(inserted_ids)

    return ExtractionResult(
        processed=processed,
        extracted=extracted,
        skipped=skipped,
        no_match=no_match,
        failed=failed,
        inserted_records=inserted_total,
        new_record_ids=new_record_ids,
    )
