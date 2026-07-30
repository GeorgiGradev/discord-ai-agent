"""OpenAI embedding client with batching."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from assistant.config import Settings

logger = logging.getLogger(__name__)

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"

# text-embedding-3-small list pricing (USD per million tokens).
EMBED_USD_PER_MTOK = 0.02

EMBEDDING_DIMENSIONS = 1536


class EmbeddingError(Exception):
    """Raised when embedding API calls fail or are misconfigured."""


@dataclass(frozen=True)
class EmbedUsage:
    model: str
    input_tokens: int
    api_calls: int = 1

    def estimated_cost_usd(self, *, usd_per_mtok: float = EMBED_USD_PER_MTOK) -> float:
        return self.input_tokens * usd_per_mtok / 1_000_000


def _merge_usage(total: EmbedUsage, batch: EmbedUsage) -> EmbedUsage:
    return EmbedUsage(
        model=batch.model or total.model,
        input_tokens=total.input_tokens + batch.input_tokens,
        api_calls=total.api_calls + batch.api_calls,
    )


async def _embed_batch(texts: list[str], settings: Settings) -> tuple[list[list[float]], EmbedUsage]:
    if not settings.openai_api_key:
        raise EmbeddingError("OPENAI_API_KEY is not configured")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            OPENAI_EMBEDDINGS_URL,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_embedding_model,
                "input": texts,
                "dimensions": EMBEDDING_DIMENSIONS,
            },
        )
        response.raise_for_status()
        payload = response.json()

    data = payload.get("data")
    if not isinstance(data, list):
        raise EmbeddingError("OpenAI embeddings response missing data array")

    ordered = sorted(data, key=lambda item: item.get("index", 0))
    vectors: list[list[float]] = []
    for item in ordered:
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            raise EmbeddingError("OpenAI embeddings response item missing embedding vector")
        vectors.append([float(value) for value in embedding])

    usage_raw = payload.get("usage") or {}
    total_tokens = int(usage_raw.get("total_tokens") or usage_raw.get("prompt_tokens") or 0)
    return vectors, EmbedUsage(
        model=settings.openai_embedding_model,
        input_tokens=total_tokens,
    )


async def embed_texts(
    texts: list[str],
    settings: Settings,
    *,
    batch_size: int | None = None,
) -> tuple[list[list[float]], EmbedUsage]:
    """Embed one or more texts; returns vectors in the same order."""
    if not texts:
        return [], EmbedUsage(model=settings.openai_embedding_model, input_tokens=0, api_calls=0)

    effective_batch = batch_size or settings.memory_embed_batch_size
    totals = EmbedUsage(model=settings.openai_embedding_model, input_tokens=0, api_calls=0)
    all_vectors: list[list[float]] = []

    for start in range(0, len(texts), effective_batch):
        batch_texts = texts[start : start + effective_batch]
        vectors, usage = await _embed_batch(batch_texts, settings)
        all_vectors.extend(vectors)
        totals = _merge_usage(totals, usage)
        logger.debug(
            "Embedded batch %d texts model=%s tokens=%d",
            len(batch_texts),
            usage.model,
            usage.input_tokens,
        )

    return all_vectors, totals


def format_embed_cost_usd(usage: EmbedUsage) -> str:
    return f"${usage.estimated_cost_usd():.4f}"
