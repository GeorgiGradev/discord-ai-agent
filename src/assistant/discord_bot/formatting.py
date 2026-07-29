"""Format payment and event records for Discord."""

from __future__ import annotations

from assistant.db.models import CareerEvent, ConferenceEvent, PaymentRecord
from assistant.domain.payments import RecordType, format_amount_minor
from assistant.extraction.events.pipeline import FailedEventExtraction
from assistant.extraction.pipeline import FailedExtraction


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


def format_extraction_failure(failure: FailedExtraction) -> str:
    subject = failure.subject or "(без тема)"
    sender = failure.sender or "неизвестен"
    return (
        f"**Extraction failed** `[m:{failure.message_id}]`\n"
        f"_{subject[:120]}_\n"
        f"`{sender}` · {failure.reason}"
    )


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


def _format_quote(quote: str, max_len: int = 160) -> str:
    cleaned = quote.strip().replace("\n", " ")
    if len(cleaned) > max_len:
        return cleaned[: max_len - 1] + "…"
    return cleaned


def _attendance_label(mode: str | None) -> str:
    labels = {
        "ONLINE": "🌐 Online",
        "IN_PERSON": "📍 Присъствено",
        "HYBRID": "🔀 Hybrid",
        "UNKNOWN": "❓ Неизвестен",
    }
    return labels.get(mode or "", mode or "")


def _humanize_event_failure(reason: str) -> str:
    lowered = reason.lower()
    if "evidence quote not found" in lowered:
        return "Цитатът не съвпада с текста на писмото (копирай точно от body-то)."
    if "price" in lowered and "not in evidence quote" in lowered:
        return "Цената не е в цитата — събитието не е записано."
    if "empty evidence quote" in lowered:
        return "Липсва evidence quote."
    if "invalid" in lowered and "date" in lowered:
        return "Невалидна дата в отговора на модела."
    if len(reason) > 140:
        return reason[:139] + "…"
    return reason


def format_conference_event(record: ConferenceEvent) -> str:
    meta_parts: list[str] = []
    if record.starts_on:
        period = record.starts_on.strftime("%d.%m.%Y")
        if record.ends_on and record.ends_on != record.starts_on:
            period = f"{period} → {record.ends_on.strftime('%d.%m.%Y')}"
        meta_parts.append(f"📅 {period}")
    if record.attendance_mode:
        meta_parts.append(_attendance_label(record.attendance_mode))
    if record.price_minor is not None and record.currency:
        meta_parts.append(f"💶 {format_amount_minor(record.price_minor, record.currency)}")
    elif record.price_raw:
        meta_parts.append(f"💶 {record.price_raw}")

    lines = [f"🎟 **{record.name}** `[ev:c:{record.id}]`"]
    if meta_parts:
        lines.append(" · ".join(meta_parts))
    if record.location:
        lines.append(f"📍 {record.location[:120]}")
    if record.registration_deadline:
        lines.append(f"⏰ Регистрация до **{record.registration_deadline.strftime('%d.%m.%Y')}**")
    if record.cfp_deadline:
        lines.append(f"📝 CFP до **{record.cfp_deadline.strftime('%d.%m.%Y')}**")
    lines.append(f"> {_format_quote(record.evidence_quote)}")
    return "\n".join(lines)


def format_career_event(record: CareerEvent) -> str:
    title = record.position or record.event_type.replace("_", " ").title()
    lines = [f"💼 **{record.company}** — {title} `[ev:r:{record.id}]`"]
    if record.event_date:
        lines.append(f"📅 {record.event_date.strftime('%d.%m.%Y')}")
    if record.deadline:
        lines.append(f"⏰ Краен срок **{record.deadline.strftime('%d.%m.%Y')}**")
    if record.next_step:
        lines.append(f"👉 _{record.next_step[:120]}_")
    lines.append(f"> {_format_quote(record.evidence_quote)}")
    return "\n".join(lines)


def format_event_extraction_failure(failure: FailedEventExtraction) -> str:
    subject = failure.subject or "(без тема)"
    return (
        f"❌ **Неуспешно извлечение** `[m:{failure.message_id}]`\n"
        f"_{subject[:120]}_\n"
        f"{_humanize_event_failure(failure.reason)}"
    )


def format_event_extraction_summary(
    *,
    processed: int,
    extracted: int,
    skipped: int,
    no_match: int,
    failed: int,
    inserted_conference: int,
    inserted_career: int,
) -> str:
    return (
        "📋 **Event extraction завърши**\n"
        f"- обработени: **{processed}** · извлечени: **{extracted}** "
        f"({inserted_conference} conf / {inserted_career} career)\n"
        f"- без събития: {no_match} · грешки: **{failed}** · пропуснати: {skipped}"
    )
