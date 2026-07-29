"""Persist extracted payment records with deduplication."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from assistant.db.models import PaymentRecord, RawMessage
from assistant.domain.payments import normalize_payee
from assistant.extraction.base import ExtractedRecord


def _period_month(received_at: datetime | None, record: ExtractedRecord) -> str | None:
    if record.period_month:
        return record.period_month
    if received_at is None:
        return None
    local = received_at.astimezone(UTC)
    return local.strftime("%Y-%m")


async def persist_extracted_records(
    session: AsyncSession,
    *,
    message: RawMessage,
    records: list[ExtractedRecord],
    extractor_name: str,
) -> list[int]:
    inserted_ids: list[int] = []
    for record in records:
        subscriber = record.subscriber_number or ""
        period = _period_month(message.received_at, record)
        payee_normalized = normalize_payee(record.payee)

        stmt = (
            insert(PaymentRecord)
            .values(
                raw_message_id=message.id,
                account_id=message.account_id,
                record_type=record.record_type.value,
                payee=record.payee,
                payee_normalized=payee_normalized,
                subscriber_number=subscriber,
                description=record.description,
                amount_minor=record.amount_minor,
                currency=record.currency.upper()[:3],
                amount_raw=record.amount_raw,
                due_date=record.due_date,
                payment_status=record.payment_status,
                period_month=period,
                evidence_quote=record.evidence_quote,
                extractor_name=extractor_name,
            )
            .on_conflict_do_nothing(constraint="uq_payment_dedup")
            .returning(PaymentRecord.id)
        )
        result = await session.execute(stmt)
        row_id = result.scalar_one_or_none()
        if row_id is not None:
            inserted_ids.append(int(row_id))

    return inserted_ids
