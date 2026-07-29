"""Anthropic Stripe receipt parser."""

from __future__ import annotations

import re

from assistant.domain.payments import PaymentStatus, RecordType
from assistant.extraction.base import ExtractedRecord, MessageView
from assistant.extraction.money import find_verbatim_quote, parse_money_token
from assistant.extraction.validation import validate_records

SENDER = "invoice+statements@mail.anthropic.com"
TOTAL_RE = re.compile(r"Amount paid\s+(€[\d.,]+)", re.IGNORECASE)
FALLBACK_TOTAL_RE = re.compile(r"(?<!excluding tax )Total\s+(€[\d.,]+)", re.IGNORECASE)
RECEIPT_NUM_RE = re.compile(r"Receipt #(\S+)")
PRODUCT_RE = re.compile(r"Claude[^\n€$]+", re.IGNORECASE)


class AnthropicReceiptExtractor:
    name = "anthropic_receipt"

    def matches(self, msg: MessageView) -> bool:
        return (msg.sender or "").lower() == SENDER

    def extract(self, msg: MessageView) -> list[ExtractedRecord]:
        text = msg.text_body or ""
        if not text:
            return []

        total_match = TOTAL_RE.search(text) or FALLBACK_TOTAL_RE.search(text)
        if not total_match:
            return []

        amount_token = total_match.group(1)
        amount_minor, currency, amount_raw = parse_money_token(amount_token)
        quote = find_verbatim_quote(amount_token, text=msg.text_body, html=msg.html_body)

        receipt_number = None
        receipt_match = RECEIPT_NUM_RE.search(text)
        if receipt_match:
            receipt_number = receipt_match.group(1)
        elif msg.subject:
            subject_match = re.search(r"#(\S+)", msg.subject)
            if subject_match:
                receipt_number = subject_match.group(1)

        description = msg.subject
        product_match = PRODUCT_RE.search(text)
        if product_match:
            description = product_match.group(0).strip()

        record = ExtractedRecord(
            record_type=RecordType.RECEIPT,
            payee="Anthropic, PBC",
            subscriber_number=receipt_number,
            description=description,
            amount_minor=amount_minor,
            currency=currency,
            amount_raw=amount_raw,
            due_date=None,
            payment_status=PaymentStatus.PAID.value,
            evidence_quote=quote,
        )
        return validate_records(msg, [record])
