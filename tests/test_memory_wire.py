"""Tests for memory wiring (C1.3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from assistant.memory.embed import EmbedUsage
from assistant.memory.index import IndexResult
from assistant.memory.wire import (
    MemoryIndexSummary,
    format_memory_index_summary,
    index_all_payment_records,
    index_payment_record_ids,
)


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


class FakeScalars:
    def __init__(self, values: list[int]) -> None:
        self._values = values

    def all(self) -> list[int]:
        return self._values


class FakeSession:
    def __init__(self, record_ids: list[int] | None = None) -> None:
        self.record_ids = record_ids or []

    async def get(self, _model, record_id: int):
        if record_id in self.record_ids:
            return object()
        return None

    async def scalars(self, _stmt):
        return FakeScalars(self.record_ids)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class FakeSessionFactory:
    def __init__(self, record_ids: list[int] | None = None) -> None:
        self.record_ids = record_ids or []

    def __call__(self):
        return FakeSession(self.record_ids)


def test_format_memory_index_summary_unavailable():
    text = format_memory_index_summary(MemoryIndexSummary(unavailable=True))
    assert "OPENAI_API_KEY" in text


def test_format_memory_index_summary_counts():
    text = format_memory_index_summary(
        MemoryIndexSummary(inserted=2, updated=1, skipped=3, failed=0, total_tokens=42)
    )
    assert "нови **2**" in text
    assert "Embedding tokens: 42" in text


@pytest.mark.asyncio
async def test_index_payment_record_ids_skips_without_api_key():
    summary = await index_payment_record_ids(
        FakeSessionFactory([1, 2]),
        _settings(OPENAI_API_KEY=None),
        [1, 2],
    )
    assert summary.unavailable is True
    assert summary.skipped == 2


@pytest.mark.asyncio
async def test_index_payment_record_ids_indexes_records():
    usage = EmbedUsage(model="text-embedding-3-small", input_tokens=10, api_calls=1)

    with patch(
        "assistant.memory.wire.index_payment_record",
        AsyncMock(
            side_effect=[
                IndexResult(memory_id=1, action="inserted", usage=usage),
                IndexResult(memory_id=2, action="skipped", usage=usage),
            ]
        ),
    ) as mock_index:
        summary = await index_payment_record_ids(
            FakeSessionFactory([1, 2]),
            _settings(),
            [1, 2],
        )

    assert mock_index.await_count == 2
    assert summary.inserted == 1
    assert summary.skipped == 1
    assert summary.total_tokens == 10


@pytest.mark.asyncio
async def test_index_all_payment_records_loads_ids_from_db():
    factory = FakeSessionFactory([10, 11, 12])
    settings = _settings()

    with patch(
        "assistant.memory.wire.index_payment_record_ids",
        AsyncMock(return_value=MemoryIndexSummary(inserted=3)),
    ) as mock_batch:
        summary = await index_all_payment_records(factory, settings)

    mock_batch.assert_awaited_once_with(factory, settings, [10, 11, 12])
    assert summary.inserted == 3
