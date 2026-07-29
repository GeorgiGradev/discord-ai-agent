"""Opportunistic JSON-LD invoice extraction from email HTML."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from assistant.domain.payments import RecordType
from assistant.extraction.base import ExtractedRecord, MessageView


def _parse_jsonld_blocks(html: str | None) -> list[dict]:
    if not html:
        return []
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    blocks: list[dict] = []
    for match in pattern.finditer(html):
        raw = match.group(1).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            blocks.append(payload)
        elif isinstance(payload, list):
            blocks.extend(item for item in payload if isinstance(item, dict))
    return blocks


def _money_from_value(value: object) -> tuple[int, str, str] | None:
    if isinstance(value, (int, float, Decimal)):
        amount_raw = str(value)
        return int(Decimal(amount_raw) * 100), "USD", amount_raw
    if isinstance(value, dict):
        amount_raw = str(value.get("value") or value.get("price") or "")
        currency = str(value.get("currency") or "USD").upper()[:3]
        try:
            amount_minor = int(Decimal(amount_raw.replace(",", ".")) * 100)
        except (InvalidOperation, ValueError):
            return None
        return amount_minor, currency, amount_raw
    return None


def _record_type_for(schema_type: str) -> RecordType | None:
    lowered = schema_type.lower()
    if "invoice" in lowered:
        return RecordType.INVOICE_WITH_DUE_DATE
    if "order" in lowered:
        return RecordType.RECEIPT
    return None


def extract_jsonld(msg: MessageView) -> list[ExtractedRecord]:
    records: list[ExtractedRecord] = []
    for block in _parse_jsonld_blocks(msg.html_body):
        schema_type = str(block.get("@type") or "")
        record_type = _record_type_for(schema_type)
        if record_type is None:
            continue

        total = block.get("totalPaymentDue") or block.get("totalPrice") or block.get("price")
        parsed = _money_from_value(total)
        if parsed is None:
            continue
        amount_minor, currency, amount_raw = parsed

        provider = block.get("provider") or block.get("seller") or block.get("merchant")
        payee = "Unknown"
        if isinstance(provider, dict):
            payee = str(provider.get("name") or payee)
        elif provider:
            payee = str(provider)

        due_date: date | None = None
        due_raw = block.get("paymentDue") or block.get("dueDate")
        if isinstance(due_raw, str) and len(due_raw) >= 10:
            try:
                due_date = date.fromisoformat(due_raw[:10])
            except ValueError:
                due_date = None

        quote = json.dumps(block, ensure_ascii=False)[:500]
        records.append(
            ExtractedRecord(
                record_type=record_type,
                payee=payee,
                subscriber_number=None,
                description=msg.subject,
                amount_minor=amount_minor,
                currency=currency,
                amount_raw=amount_raw,
                due_date=due_date,
                payment_status=None,
                evidence_quote=quote,
            )
        )
    return records
