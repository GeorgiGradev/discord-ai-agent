"""Format payment records for Discord."""

from __future__ import annotations

from assistant.db.models import PaymentRecord
from assistant.domain.payments import RecordType, format_amount_minor


def format_payment_record(record: PaymentRecord) -> str:
    amount = format_amount_minor(record.amount_minor, record.currency)
    lines = [
        f"**{record.payee}** `[p:{record.id}]` · {amount}",
        f"`{record.record_type}` · извлечено от `{record.extractor_name}`",
    ]
    if record.description:
        lines.append(f"_{record.description[:120]}_")
    if record.record_type == RecordType.PENDING_OBLIGATION.value:
        lines.append("Срок: **неизвестен** · Статус: **неизвестен**")
    elif record.due_date:
        lines.append(f"Срок: **{record.due_date.isoformat()}**")
    if record.evidence_quote:
        quote = record.evidence_quote.strip().replace("\n", " ")
        if len(quote) > 160:
            quote = quote[:159] + "…"
        lines.append(f"> {quote}")
    return "\n".join(lines)


def format_extraction_summary(
    *,
    processed: int,
    extracted: int,
    skipped: int,
    no_match: int,
    failed: int,
    inserted_records: int,
) -> str:
    return (
        "**Extraction завърши**\n"
        f"- обработени: {processed}\n"
        f"- извлечени: {extracted} ({inserted_records} нови записа)\n"
        f"- пропуснати: {skipped}\n"
        f"- без шаблон: {no_match}\n"
        f"- грешки: {failed}"
    )
