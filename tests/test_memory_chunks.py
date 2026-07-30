"""Tests for memory chunk builders."""

from datetime import date

from assistant.db.models import PaymentRecord
from assistant.domain.memory import MemoryKind
from assistant.memory.chunks import payment_record_to_chunk


def _payment(**overrides) -> PaymentRecord:
    defaults = {
        "id": 42,
        "raw_message_id": 7,
        "account_id": 1,
        "record_type": "PENDING_OBLIGATION",
        "payee": "ВиК Хасково",
        "payee_normalized": "вик хасково",
        "subscriber_number": "АП.8",
        "description": "Вода и канализация",
        "amount_minor": 848,
        "currency": "EUR",
        "amount_raw": "8.48 EUR",
        "due_date": date(2026, 8, 15),
        "payment_status": "UNPAID",
        "period_month": "2026-07",
        "evidence_quote": "Общо за плащане 8.48 EUR до 15.08.2026",
        "extractor_name": "ubb_bitovi_smetki",
    }
    defaults.update(overrides)
    return PaymentRecord(**defaults)


def test_payment_record_to_chunk_includes_core_fields():
    chunk = payment_record_to_chunk(_payment())

    assert chunk.kind == MemoryKind.PAYMENT
    assert chunk.source_id == "p:42"
    assert "ВиК Хасково" in chunk.content
    assert "8.48 EUR" in chunk.content
    assert "АП.8" in chunk.content
    assert chunk.metadata["record_id"] == 42
    assert chunk.metadata["content_hash"] == chunk.content_hash


def test_payment_record_to_chunk_is_stable_for_same_input():
    record = _payment()
    first = payment_record_to_chunk(record)
    second = payment_record_to_chunk(record)

    assert first.content == second.content
    assert first.content_hash == second.content_hash
