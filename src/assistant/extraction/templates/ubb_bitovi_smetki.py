"""UBB BitoviSmetki utility bill table parser."""

from __future__ import annotations

from selectolax.parser import HTMLParser

from assistant.domain.payments import RecordType
from assistant.extraction.base import ExtractedRecord, MessageView
from assistant.extraction.money import find_verbatim_quote, parse_money_token
from assistant.extraction.validation import validate_records

SENDER = "bitovismetki@ubb.bg"
TABLE_ID = "TableOblg"
HEADER_MARKERS = ("име на компания", "company")


class UbbBitoviSmetkiExtractor:
    name = "ubb_bitovi_smetki"

    def matches(self, msg: MessageView) -> bool:
        return (msg.sender or "").lower() == SENDER

    def extract(self, msg: MessageView) -> list[ExtractedRecord]:
        if not msg.html_body:
            return []

        tree = HTMLParser(msg.html_body)
        table = tree.css_first(f"#{TABLE_ID}")
        if table is None:
            return []

        records: list[ExtractedRecord] = []
        for row in table.css("tr"):
            cells = [cell.text(strip=True) for cell in row.css("td")]
            if len(cells) != 4:
                continue
            if cells[0].lower() in HEADER_MARKERS:
                continue

            company, subscriber, description, amount_cell = cells
            amount_minor, currency, amount_raw = parse_money_token(amount_cell)
            quote = find_verbatim_quote(amount_cell, text=msg.text_body, html=msg.html_body)

            records.append(
                ExtractedRecord(
                    record_type=RecordType.PENDING_OBLIGATION,
                    payee=company,
                    subscriber_number=subscriber,
                    description=description,
                    amount_minor=amount_minor,
                    currency=currency,
                    amount_raw=amount_raw,
                    due_date=None,
                    payment_status=None,
                    evidence_quote=quote,
                )
            )

        return validate_records(msg, records)
