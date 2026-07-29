"""Payment domain types and money helpers."""

from __future__ import annotations

import enum
import re
from decimal import Decimal, InvalidOperation


class RecordType(str, enum.Enum):
    PENDING_OBLIGATION = "PENDING_OBLIGATION"
    RECEIPT = "RECEIPT"
    INVOICE_WITH_DUE_DATE = "INVOICE_WITH_DUE_DATE"
    RENEWAL_NOTICE = "RENEWAL_NOTICE"


class PaymentStatus(str, enum.Enum):
    PAID = "PAID"
    UNPAID = "UNPAID"
    UNKNOWN = "UNKNOWN"


def normalize_payee(value: str) -> str:
    cleaned = value.strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def parse_amount_minor(amount_raw: str, currency: str) -> int:
    """Convert decimal string to minor units (cents/stotinki)."""
    normalized = amount_raw.strip().replace(",", ".")
    normalized = re.sub(r"[^\d.]", "", normalized)
    if not normalized:
        raise ValueError(f"cannot parse amount: {amount_raw!r}")

    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"cannot parse amount: {amount_raw!r}") from exc

    if currency.upper() in {"JPY", "KRW"}:
        return int(amount)
    return int(amount * 100)


def format_amount_minor(amount_minor: int, currency: str) -> str:
    code = currency.upper()
    if code in {"JPY", "KRW"}:
        return f"{amount_minor} {code}"
    whole = amount_minor // 100
    frac = abs(amount_minor % 100)
    return f"{whole}.{frac:02d} {code}"
