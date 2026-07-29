"""Tests for LLM fallback extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from assistant.config import Settings
from assistant.domain.payments import RecordType
from assistant.extraction.base import ExtractedRecord, MessageView
from assistant.extraction.llm_cost import LlmUsage, LlmUsageTotals
from assistant.extraction.llm_fallback import LlmExtractionPayload, LlmPaymentRecord, extract_with_llm
from assistant.extraction.pipeline import run_cascade, run_deterministic_cascade


def _msg(**kwargs) -> MessageView:
    defaults = {
        "id": 42,
        "account_id": 1,
        "gm_msgid": "test-llm",
        "sender": "billing@example-saas.com",
        "subject": "Receipt #9999-0000-0002",
        "labels": ["Payment"],
        "received_at": None,
        "text_body": None,
        "html_body": None,
    }
    defaults.update(kwargs)
    return MessageView(**defaults)


def _settings(**overrides) -> Settings:
    from cryptography.fernet import Fernet

    base = {
        "DISCORD_BOT_TOKEN": "token",
        "DISCORD_ALLOWED_USER_IDS": "1",
        "DISCORD_GUILD_ID": "1",
        "DISCORD_CHANNEL_GENERAL": "1",
        "DISCORD_CHANNEL_CHAT": "1",
        "DISCORD_CHANNEL_PAYMENTS": "1",
        "DISCORD_CHANNEL_EVENTS": "1",
        "DISCORD_CHANNEL_JOURNAL": "1",
        "FERNET_KEY": Fernet.generate_key().decode(),
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
        "ACCOUNT_PRIMARY_EMAIL": "a@example.com",
        "ACCOUNT_PRIMARY_IMAP_PASSWORD": "pw",
        "ACCOUNT_PRIMARY_SYNC_LABELS": "Payment",
        "ACCOUNT_SECONDARY_EMAIL": "b@example.com",
        "ACCOUNT_SECONDARY_IMAP_PASSWORD": "pw2",
        "ACCOUNT_SECONDARY_SYNC_LABELS": "Payment",
        "ANTHROPIC_API_KEY": "test-key",
        "LLM_EXTRACTION_ENABLED": "true",
    }
    base.update(overrides)
    return Settings(**base)


def _mock_llm_response(payload: LlmExtractionPayload) -> tuple[LlmExtractionPayload, LlmUsage]:
    return payload, LlmUsage(model="claude-haiku-test", input_tokens=500, output_tokens=120)


@pytest.mark.asyncio
async def test_extract_with_llm_returns_validated_records(monkeypatch):
    body = (
        "Receipt from Example SaaS\n"
        "Amount paid 18.00 EUR on January 10, 2026\n"
        "Receipt #9999-0000-0002"
    )
    msg = _msg(text_body=body)
    settings = _settings()

    mock_call = AsyncMock(
        return_value=_mock_llm_response(
            LlmExtractionPayload(
                records=[
                    LlmPaymentRecord(
                        record_type="RECEIPT",
                        payee="Example SaaS",
                        subscriber_number="9999-0000-0002",
                        description="Pro plan",
                        amount_raw="18.00 EUR",
                        currency="EUR",
                        payment_status="PAID",
                        evidence_quote="Amount paid 18.00 EUR",
                    )
                ]
            )
        )
    )
    monkeypatch.setattr("assistant.extraction.llm_fallback._call_anthropic", mock_call)

    records, usage = await extract_with_llm(msg, settings)

    assert len(records) == 1
    record = records[0]
    assert record.record_type == RecordType.RECEIPT
    assert record.amount_minor == 1800
    assert record.evidence_quote == "Amount paid 18.00 EUR"
    assert usage.api_calls == 1
    assert usage.input_tokens == 500
    mock_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_with_llm_rejects_hallucinated_quote(monkeypatch):
    msg = _msg(text_body="Total due: 10.00 EUR")
    settings = _settings()

    mock_call = AsyncMock(
        return_value=_mock_llm_response(
            LlmExtractionPayload(
                records=[
                    LlmPaymentRecord(
                        record_type="PENDING_OBLIGATION",
                        payee="Unknown Co",
                        amount_raw="99.00 EUR",
                        currency="EUR",
                        evidence_quote="Total due: 99.00 EUR",
                    )
                ]
            )
        )
    )
    monkeypatch.setattr("assistant.extraction.llm_fallback._call_anthropic", mock_call)

    records, usage = await extract_with_llm(msg, settings)

    assert records == []
    assert usage.api_calls == 2  # citation_max_retries=1 → 2 attempts
    assert mock_call.await_count == 2


@pytest.mark.asyncio
async def test_run_cascade_uses_llm_after_template_miss(monkeypatch):
    msg = _msg(
        sender="BitoviSmetki@ubb.bg",
        html_body="<html><body><p>Notification without payment table.</p></body></html>",
    )
    settings = _settings()

    deterministic = run_deterministic_cascade(msg)
    assert deterministic[0] == []
    assert deterministic[2] is True

    llm_record = ExtractedRecord(
        record_type=RecordType.PENDING_OBLIGATION,
        payee="Example Utility",
        subscriber_number="123",
        description="Electricity",
        amount_minor=1050,
        currency="EUR",
        amount_raw="10.50 EUR",
        due_date=None,
        payment_status=None,
        evidence_quote="10.50 EUR",
    )
    usage = LlmUsageTotals()
    usage.add(LlmUsage(model="claude-haiku-test", input_tokens=100, output_tokens=20))
    mock_extract = AsyncMock(return_value=([llm_record], usage))
    monkeypatch.setattr("assistant.extraction.pipeline.extract_with_llm", mock_extract)

    records, extractor_name, template_miss, llm_usage = await run_cascade(msg, settings)

    assert records == [llm_record]
    assert extractor_name == "llm_haiku"
    assert template_miss is False
    assert llm_usage.api_calls == 1
    mock_extract.assert_awaited_once_with(msg, settings)


@pytest.mark.asyncio
async def test_run_cascade_skips_llm_without_api_key():
    msg = _msg(
        sender="BitoviSmetki@ubb.bg",
        html_body="<html><body><p>Notification without payment table.</p></body></html>",
    )
    settings = _settings(ANTHROPIC_API_KEY="")

    records, _extractor_name, template_miss, llm_usage = await run_cascade(msg, settings)

    assert records == []
    assert template_miss is True
    assert llm_usage.has_usage is False
