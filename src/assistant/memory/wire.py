"""Wire vector memory indexing into payment extraction and backfill."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from assistant.config import Settings
from assistant.db.models import PaymentRecord
from assistant.memory.index import index_payment_record

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryIndexSummary:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    total_tokens: int = 0
    unavailable: bool = False

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.skipped + self.failed


def format_memory_index_summary(summary: MemoryIndexSummary) -> str:
    if summary.unavailable:
        return "🧠 **Memory reindex:** пропуснато — липсва `OPENAI_API_KEY`."

    lines = [
        "🧠 **Memory reindex завърши**",
        (
            f"нови **{summary.inserted}** · обновени **{summary.updated}** · "
            f"пропуснати **{summary.skipped}** · грешки **{summary.failed}**"
        ),
    ]
    if summary.total_tokens > 0:
        lines.append(f"_Embedding tokens: {summary.total_tokens}_")
    return "\n".join(lines)


def _merge_summary(base: MemoryIndexSummary, action: str, *, tokens: int = 0) -> MemoryIndexSummary:
    if action == "inserted":
        return MemoryIndexSummary(
            inserted=base.inserted + 1,
            updated=base.updated,
            skipped=base.skipped,
            failed=base.failed,
            total_tokens=base.total_tokens + tokens,
        )
    if action == "updated":
        return MemoryIndexSummary(
            inserted=base.inserted,
            updated=base.updated + 1,
            skipped=base.skipped,
            failed=base.failed,
            total_tokens=base.total_tokens + tokens,
        )
    if action == "skipped":
        return MemoryIndexSummary(
            inserted=base.inserted,
            updated=base.updated,
            skipped=base.skipped + 1,
            failed=base.failed,
            total_tokens=base.total_tokens,
        )
    return base


async def index_payment_record_ids(
    session_factory: async_sessionmaker,
    settings: Settings,
    record_ids: list[int],
) -> MemoryIndexSummary:
    """Index specific payment records by id (skips unchanged content hashes)."""
    if not record_ids:
        return MemoryIndexSummary()

    if not settings.openai_api_key:
        logger.warning(
            "Memory indexing skipped for %d record(s): OPENAI_API_KEY not set",
            len(record_ids),
        )
        return MemoryIndexSummary(skipped=len(record_ids), unavailable=True)

    summary = MemoryIndexSummary()
    for record_id in record_ids:
        try:
            async with session_factory() as session:
                record = await session.get(PaymentRecord, record_id)
                if record is None:
                    logger.warning("Memory index: payment record id=%d not found", record_id)
                    summary = MemoryIndexSummary(
                        inserted=summary.inserted,
                        updated=summary.updated,
                        skipped=summary.skipped,
                        failed=summary.failed + 1,
                        total_tokens=summary.total_tokens,
                    )
                    continue
                result = await index_payment_record(session, record, settings)
            summary = _merge_summary(summary, result.action, tokens=result.usage.input_tokens)
        except Exception:
            logger.exception("Memory index failed for payment record id=%d", record_id)
            summary = MemoryIndexSummary(
                inserted=summary.inserted,
                updated=summary.updated,
                skipped=summary.skipped,
                failed=summary.failed + 1,
                total_tokens=summary.total_tokens,
            )
    return summary


async def index_all_payment_records(
    session_factory: async_sessionmaker,
    settings: Settings,
) -> MemoryIndexSummary:
    """Index every payment record in the database."""
    if not settings.openai_api_key:
        logger.warning("Memory backfill skipped: OPENAI_API_KEY not set")
        return MemoryIndexSummary(unavailable=True)

    async with session_factory() as session:
        record_ids = (
            await session.scalars(select(PaymentRecord.id).order_by(PaymentRecord.id.asc()))
        ).all()
    logger.info("Memory backfill starting for %d payment record(s)", len(record_ids))
    return await index_payment_record_ids(session_factory, settings, record_ids)
