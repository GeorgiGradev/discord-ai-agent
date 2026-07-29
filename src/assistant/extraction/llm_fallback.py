"""LLM fallback extraction with verbatim validation (B4)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser

from assistant.config import Settings
from assistant.domain.payments import RecordType
from assistant.extraction.base import ExtractedRecord, MessageView
from assistant.extraction.money import parse_money_token
from assistant.extraction.validation import ExtractionRejected, validate_records

logger = logging.getLogger(__name__)

MAX_BODY_CHARS = 14_000
TOOL_NAME = "extract_payment_records"

RecordTypeLiteral = Literal[
    "PENDING_OBLIGATION",
    "RECEIPT",
    "INVOICE_WITH_DUE_DATE",
    "RENEWAL_NOTICE",
]


class LlmPaymentRecord(BaseModel):
    record_type: RecordTypeLiteral
    payee: str
    subscriber_number: str | None = None
    description: str | None = None
    amount_raw: str = Field(
        description="Exact amount substring copied from the email body, e.g. '€21.60' or '8.48 eur'"
    )
    currency: str = Field(default="EUR", description="ISO 4217 currency code")
    due_date: str | None = Field(
        default=None, description="ISO date YYYY-MM-DD when explicitly stated, otherwise null"
    )
    payment_status: str | None = Field(
        default=None, description="PAID, UNPAID, or null when unknown"
    )
    evidence_quote: str = Field(
        description="Exact verbatim substring from the email body that supports this record"
    )


class LlmExtractionPayload(BaseModel):
    records: list[LlmPaymentRecord] = Field(default_factory=list)


SYSTEM_PROMPT = """You extract structured payment records from personal emails.

Rules:
- Return zero records if the email is not about a payment, invoice, receipt, or bill.
- Never invent amounts, dates, payees, or reference numbers.
- evidence_quote MUST be copied exactly from the email body (character-for-character).
- amount_raw MUST appear inside evidence_quote exactly as written in the email.
- For utility bills without a due date, use record_type PENDING_OBLIGATION and due_date null.
- For paid receipts, use record_type RECEIPT and payment_status PAID when clearly paid.
- Leave due_date and payment_status null when not explicitly stated — do not guess.
- subscriber_number is optional (receipt number, account number, etc.) when present.
"""


def message_body_for_llm(msg: MessageView) -> str:
    if msg.text_body and msg.text_body.strip():
        body = msg.text_body
    elif msg.html_body:
        body = HTMLParser(msg.html_body).text(separator="\n")
    else:
        body = ""

    body = body.strip()
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n[truncated]"
    return body


def _build_user_prompt(msg: MessageView, body: str) -> str:
    labels = ", ".join(msg.labels) if msg.labels else "(none)"
    return (
        f"From: {msg.sender or 'unknown'}\n"
        f"Subject: {msg.subject or '(no subject)'}\n"
        f"Labels: {labels}\n\n"
        f"Email body:\n---\n{body}\n---"
    )


def _parse_due_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ExtractionRejected(f"invalid due_date: {value!r}") from exc


def _to_extracted_record(item: LlmPaymentRecord) -> ExtractedRecord:
    try:
        record_type = RecordType(item.record_type)
    except ValueError as exc:
        raise ExtractionRejected(f"unknown record_type: {item.record_type!r}") from exc

    try:
        amount_minor, parsed_currency, amount_raw = parse_money_token(item.amount_raw)
    except ValueError as exc:
        raise ExtractionRejected(str(exc)) from exc

    currency = item.currency.upper()[:3] or parsed_currency
    if currency != parsed_currency and parsed_currency:
        currency = parsed_currency

    return ExtractedRecord(
        record_type=record_type,
        payee=item.payee.strip(),
        subscriber_number=item.subscriber_number,
        description=item.description,
        amount_minor=amount_minor,
        currency=currency,
        amount_raw=amount_raw,
        due_date=_parse_due_date(item.due_date),
        payment_status=item.payment_status,
        evidence_quote=item.evidence_quote,
    )


def _parse_tool_payload(data: object) -> LlmExtractionPayload:
    if not isinstance(data, dict):
        raise ExtractionRejected("LLM tool input was not an object")
    return LlmExtractionPayload.model_validate(data)


async def _call_anthropic(msg: MessageView, settings: Settings) -> LlmExtractionPayload:
    from anthropic import AsyncAnthropic

    body = message_body_for_llm(msg)
    if not body:
        raise ExtractionRejected("message has no extractable body text")

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model_haiku,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(msg, body)}],
        tools=[
            {
                "name": TOOL_NAME,
                "description": "Extract payment records from the email",
                "input_schema": LlmExtractionPayload.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": TOOL_NAME},
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return _parse_tool_payload(block.input)

    raise ExtractionRejected("LLM did not return structured extraction")


async def extract_with_llm(msg: MessageView, settings: Settings) -> list[ExtractedRecord]:
    """Run Haiku extraction with retries on verbatim validation failure."""
    if not settings.anthropic_api_key:
        raise ExtractionRejected("ANTHROPIC_API_KEY is not configured")

    max_attempts = max(1, settings.citation_max_retries + 1)
    last_error: ExtractionRejected | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            payload = await _call_anthropic(msg, settings)
            if not payload.records:
                return []
            records = [_to_extracted_record(item) for item in payload.records]
            return validate_records(msg, records)
        except ExtractionRejected as exc:
            last_error = exc
            logger.warning(
                "LLM extraction attempt %d/%d rejected for message %s: %s",
                attempt,
                max_attempts,
                msg.id,
                exc,
            )

    assert last_error is not None
    raise last_error
