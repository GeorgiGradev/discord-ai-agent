"""Build searchable memory chunks from structured records."""

from __future__ import annotations

import hashlib

from assistant.db.models import PaymentRecord
from assistant.domain.memory import MemoryChunk, MemoryKind, payment_source_id
from assistant.domain.payments import format_amount_minor


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _quote_snippet(quote: str, max_len: int = 200) -> str:
    cleaned = " ".join(quote.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def payment_record_to_chunk(record: PaymentRecord) -> MemoryChunk:
    amount = format_amount_minor(record.amount_minor, record.currency)
    lines = [f"Payment ({record.record_type}): {record.payee} — {amount}"]

    if record.description:
        lines.append(f"Description: {record.description.strip()}")
    if record.due_date:
        lines.append(f"Due date: {record.due_date.isoformat()}")
    if record.payment_status:
        lines.append(f"Payment status: {record.payment_status}")
    if record.subscriber_number:
        lines.append(f"Reference: {record.subscriber_number}")
    if record.period_month:
        lines.append(f"Billing period: {record.period_month}")
    if record.amount_raw:
        lines.append(f"Amount text: {record.amount_raw}")

    lines.append(f"Evidence: {_quote_snippet(record.evidence_quote)}")
    content = "\n".join(lines)

    metadata = {
        "content_hash": _content_hash(content),
        "record_id": record.id,
        "raw_message_id": record.raw_message_id,
        "account_id": record.account_id,
        "record_type": record.record_type,
        "payee": record.payee,
        "payee_normalized": record.payee_normalized,
        "amount_minor": record.amount_minor,
        "currency": record.currency,
        "amount_raw": record.amount_raw,
        "due_date": record.due_date.isoformat() if record.due_date else None,
        "payment_status": record.payment_status,
        "subscriber_number": record.subscriber_number or None,
        "period_month": record.period_month,
        "extractor_name": record.extractor_name,
    }

    return MemoryChunk(
        kind=MemoryKind.PAYMENT,
        source_id=payment_source_id(record.id),
        content=content,
        metadata=metadata,
        content_hash=metadata["content_hash"],
    )
