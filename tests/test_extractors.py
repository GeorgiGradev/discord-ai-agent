from pathlib import Path

import pytest

from assistant.extraction.base import MessageView
from assistant.extraction.templates.anthropic_receipt import AnthropicReceiptExtractor
from assistant.extraction.templates.ubb_bitovi_smetki import UbbBitoviSmetkiExtractor
from assistant.domain.payments import RecordType

FIXTURES = Path(__file__).parent / "fixtures" / "emails"


def _msg(**kwargs) -> MessageView:
    defaults = {
        "id": 1,
        "account_id": 1,
        "gm_msgid": "test",
        "sender": None,
        "subject": None,
        "labels": [],
        "received_at": None,
        "text_body": None,
        "html_body": None,
    }
    defaults.update(kwargs)
    return MessageView(**defaults)


def test_ubb_extractor_parses_single_row():
    html = (FIXTURES / "ubb_single.html").read_text(encoding="utf-8")
    extractor = UbbBitoviSmetkiExtractor()
    msg = _msg(sender="BitoviSmetki@ubb.bg", html_body=html)

    assert extractor.matches(msg)
    records = extractor.extract(msg)

    assert len(records) == 1
    record = records[0]
    assert record.payee == "ВиК Хасково"
    assert record.subscriber_number == "145741"
    assert record.amount_minor == 848
    assert record.currency == "EUR"
    assert record.record_type == RecordType.PENDING_OBLIGATION
    assert record.due_date is None
    assert record.payment_status is None


def test_ubb_extractor_parses_multiple_rows_without_duplicates():
    html = (FIXTURES / "ubb_multi.html").read_text(encoding="utf-8")
    records = UbbBitoviSmetkiExtractor().extract(
        _msg(sender="BitoviSmetki@ubb.bg", html_body=html)
    )

    assert len(records) >= 1
    assert all(record.record_type == RecordType.PENDING_OBLIGATION for record in records)
    assert len({(record.payee, record.subscriber_number, record.amount_raw) for record in records}) == len(
        records
    )


def test_anthropic_extractor_parses_receipt():
    text = (FIXTURES / "anthropic_receipt.txt").read_text(encoding="utf-8")
    msg = _msg(
        sender="invoice+statements@mail.anthropic.com",
        subject="Your receipt from Anthropic, PBC #2118-1269-0068",
        text_body=text,
    )

    records = AnthropicReceiptExtractor().extract(msg)

    assert len(records) == 1
    record = records[0]
    assert record.amount_minor == 2160
    assert record.currency == "EUR"
    assert record.record_type == RecordType.RECEIPT
    assert record.payment_status == "PAID"
    assert record.subscriber_number == "2118-1269-0068"
