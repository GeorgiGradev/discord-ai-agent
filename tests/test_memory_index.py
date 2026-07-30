"""Tests for memory indexing."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from assistant.db.models import Memory, PaymentRecord
from assistant.memory.index import index_payment_record, upsert_memory_chunk
from assistant.memory.chunks import payment_record_to_chunk


def _settings(**overrides):
    from cryptography.fernet import Fernet

    from assistant.config import Settings

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
        "OPENAI_API_KEY": "test-openai-key",
    }
    base.update(overrides)
    return Settings(**base)


def _payment(**overrides) -> PaymentRecord:
    defaults = {
        "id": 5,
        "raw_message_id": 1,
        "account_id": 1,
        "record_type": "RECEIPT",
        "payee": "Anthropic, PBC",
        "payee_normalized": "anthropic, pbc",
        "subscriber_number": "2118-1269-0068",
        "description": "Claude Pro",
        "amount_minor": 2160,
        "currency": "EUR",
        "amount_raw": "21.60 EUR",
        "due_date": None,
        "payment_status": "PAID",
        "period_month": None,
        "evidence_quote": "Amount paid 21.60 EUR",
        "extractor_name": "anthropic_receipt",
    }
    defaults.update(overrides)
    return PaymentRecord(**defaults)


class FakeSession:
    def __init__(self) -> None:
        self.items: list[Memory] = []
        self.committed = False

    async def scalar(self, stmt):
        for item in self.items:
            kind_match = item.kind
            source_match = item.source_id
            if kind_match and source_match:
                return item
        return None

    def add(self, memory: Memory) -> None:
        memory.id = len(self.items) + 1
        self.items.append(memory)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_upsert_memory_chunk_inserts_new_memory():
    session = FakeSession()
    chunk = payment_record_to_chunk(_payment())

    memory, action = await upsert_memory_chunk(session, chunk, [0.1] * 1536)

    assert action == "inserted"
    assert memory.source_id == "p:5"
    assert len(session.items) == 1


@pytest.mark.asyncio
async def test_index_payment_record_skips_unchanged_hash():
    session = FakeSession()
    chunk = payment_record_to_chunk(_payment())
    session.items.append(
        Memory(
            id=1,
            kind=chunk.kind.value,
            content=chunk.content,
            embedding=[0.0] * 1536,
            metadata_=chunk.metadata,
            source_id=chunk.source_id,
        )
    )

    with patch("assistant.memory.index.embed_texts", AsyncMock()) as mock_embed:
        result = await index_payment_record(session, _payment(), _settings())

    mock_embed.assert_not_called()
    assert result.action == "skipped"
