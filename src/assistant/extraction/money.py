"""Parse money strings from email bodies."""

from __future__ import annotations

from assistant.domain.payments import parse_amount_minor


def parse_money_token(raw: str) -> tuple[int, str, str]:
    cleaned = " ".join(raw.split())
    lowered = cleaned.lower()

    currency = "EUR"
    numeric = cleaned

    for suffix, code in ((" eur", "EUR"), (" bgn", "BGN"), (" usd", "USD")):
        if lowered.endswith(suffix.strip()):
            currency = code
            numeric = cleaned[: -len(suffix)].strip()
            break
    else:
        if cleaned.startswith("€"):
            currency = "EUR"
            numeric = cleaned[1:].strip()
        elif cleaned.startswith("$"):
            currency = "USD"
            numeric = cleaned[1:].strip()

    amount_minor = parse_amount_minor(numeric, currency)
    return amount_minor, currency, cleaned


def find_verbatim_quote(needle: str, *, text: str | None, html: str | None) -> str:
    """Return needle if it appears verbatim in the message body."""
    if not needle:
        raise ValueError("empty evidence quote")
    for body in (text, html):
        if body and needle in body:
            return needle
    raise ValueError(f"evidence quote not found in message body: {needle!r}")
