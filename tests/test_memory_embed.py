"""Tests for OpenAI embedding client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from assistant.memory.embed import EmbeddingError, embed_texts


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
        "MEMORY_EMBED_BATCH_SIZE": "2",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_embed_texts_requires_api_key():
    settings = _settings(OPENAI_API_KEY="")
    with pytest.raises(EmbeddingError, match="OPENAI_API_KEY"):
        await embed_texts(["hello"], settings)


@pytest.mark.asyncio
async def test_embed_texts_batches_and_preserves_order():
    settings = _settings()
    calls: list[list[str]] = []

    async def fake_post(url, headers=None, json=None):
        calls.append(list(json["input"]))
        start = len(calls) - 1
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [0.1 * (start + 1), 0.2 * (index + 1)]}
                    for index, _ in enumerate(json["input"])
                ],
                "usage": {"total_tokens": 12},
            },
            request=httpx.Request("POST", url),
        )

    mock_client = AsyncMock()
    mock_client.post = fake_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("assistant.memory.embed.httpx.AsyncClient", return_value=mock_client):
        vectors, usage = await embed_texts(["a", "b", "c"], settings)

    assert calls == [["a", "b"], ["c"]]
    assert len(vectors) == 3
    assert usage.input_tokens == 24
    assert usage.api_calls == 2
