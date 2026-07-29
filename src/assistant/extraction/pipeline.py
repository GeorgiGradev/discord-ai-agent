"""Extraction cascade for pending raw messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.config import Settings
from assistant.db.models import RawMessage
from assistant.extraction.base import ExtractedRecord, MessageView
from assistant.extraction.jsonld import extract_jsonld
from assistant.extraction.llm_cost import LlmUsageTotals
from assistant.extraction.llm_fallback import extract_with_llm
from assistant.extraction.persist import persist_extracted_records
from assistant.extraction.registry import get_template_extractors
from assistant.extraction.validation import ExtractionRejected

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
class FailedExtraction:
    message_id: int
    subject: str | None
    sender: str | None
    reason: str


@dataclass(frozen=True)
class ExtractionResult:
    processed: int
    extracted: int
    skipped: int
    no_match: int
    failed: int
    inserted_records: int
    new_record_ids: list[int]
    failures: list[FailedExtraction] = field(default_factory=list)
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


def _has_payment_label(msg: MessageView) -> bool:
    return any(label.lower() == PAYMENT_LABEL for label in msg.labels)


def _is_payment_candidate(msg: MessageView) -> bool:
    if _has_payment_label(msg):
        return True
    sender = (msg.sender or "").lower()
    if any(hint in sender for hint in PAYMENT_SENDER_HINTS):
        return True
    return any(extractor.matches(msg) for extractor in get_template_extractors())


def run_deterministic_cascade(
    msg: MessageView,
) -> tuple[list[ExtractedRecord], str | None, bool]:
    """JSON-LD and template extractors only (used by eval harness)."""
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


async def run_cascade(
    msg: MessageView,
    settings: Settings | None,
) -> tuple[list[ExtractedRecord], str | None, bool, LlmUsageTotals]:
    """Deterministic cascade, then optional LLM fallback."""
    empty_usage = LlmUsageTotals()
    records, extractor_name, template_miss = run_deterministic_cascade(msg)
    if records:
        return records, extractor_name, False, empty_usage

    if settings is None or not settings.llm_extraction_enabled or not settings.anthropic_api_key:
        if template_miss and settings is not None and not settings.anthropic_api_key:
            logger.warning(
                "Template miss for message %s but ANTHROPIC_API_KEY is not set",
                msg.id,
            )
        return records, extractor_name, template_miss, empty_usage

    try:
        llm_records, llm_usage = await extract_with_llm(msg, settings)
    except ExtractionRejected as exc:
        logger.warning("LLM extraction rejected for message %s: %s", msg.id, exc)
        return [], extractor_name or "llm_haiku", True, empty_usage
    except Exception:
        logger.exception("LLM extraction failed for message %s", msg.id)
        raise

    if llm_records:
        return llm_records, "llm_haiku", False, llm_usage
    if llm_usage.has_usage:
        return [], extractor_name or "llm_haiku", True, llm_usage
    return [], extractor_name, template_miss, llm_usage


async def process_pending_messages(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings | None = None,
    *,
    batch_size: int = BATCH_SIZE,
) -> ExtractionResult:
    processed = extracted = skipped = no_match = failed = 0
    inserted_total = 0
    new_record_ids: list[int] = []
    failures: list[FailedExtraction] = []
    llm_usage_total = LlmUsageTotals()

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
            records, extractor_name, template_miss, llm_usage = await run_cascade(msg, settings)
            llm_usage_total.merge(llm_usage)
        except Exception:
            async with session_factory() as session:
                db_row = await session.get(RawMessage, row.id)
                if db_row is not None:
                    db_row.extraction_status = "failed"
                    await session.commit()
            failed += 1
            failures.append(
                FailedExtraction(
                    message_id=row.id,
                    subject=row.subject,
                    sender=row.sender,
                    reason="unexpected extraction error",
                )
            )
            continue

        if not records:
            status = "failed" if template_miss else "no_match"
            reason = (
                "template/LLM could not extract valid records"
                if template_miss
                else "no matching extractor"
            )
            async with session_factory() as session:
                db_row = await session.get(RawMessage, row.id)
                if db_row is not None:
                    db_row.extraction_status = status
                    await session.commit()
            if template_miss:
                failed += 1
                failures.append(
                    FailedExtraction(
                        message_id=row.id,
                        subject=row.subject,
                        sender=row.sender,
                        reason=reason,
                    )
                )
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
        failures=failures,
        llm_usage=llm_usage_total,
    )
