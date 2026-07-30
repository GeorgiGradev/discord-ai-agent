"""Upsert memory chunks with embeddings."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assistant.config import Settings
from assistant.db.models import Memory, PaymentRecord
from assistant.domain.memory import MemoryChunk
from assistant.memory.chunks import payment_record_to_chunk
from assistant.memory.embed import EmbedUsage, embed_texts

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexResult:
    memory_id: int | None
    action: str  # inserted | updated | skipped
    usage: EmbedUsage


async def upsert_memory_chunk(
    session: AsyncSession,
    chunk: MemoryChunk,
    embedding: list[float],
) -> tuple[Memory, str]:
    existing = await session.scalar(
        select(Memory).where(
            Memory.kind == chunk.kind.value,
            Memory.source_id == chunk.source_id,
        )
    )
    if existing is None:
        memory = Memory(
            kind=chunk.kind.value,
            content=chunk.content,
            embedding=embedding,
            metadata_=chunk.metadata,
            source_id=chunk.source_id,
        )
        session.add(memory)
        await session.flush()
        return memory, "inserted"

    if existing.metadata_.get("content_hash") == chunk.content_hash:
        return existing, "skipped"

    existing.content = chunk.content
    existing.embedding = embedding
    existing.metadata_ = chunk.metadata
    await session.flush()
    return existing, "updated"


async def index_payment_record(
    session: AsyncSession,
    record: PaymentRecord,
    settings: Settings,
) -> IndexResult:
    chunk = payment_record_to_chunk(record)
    existing = await session.scalar(
        select(Memory).where(
            Memory.kind == chunk.kind.value,
            Memory.source_id == chunk.source_id,
        )
    )
    if existing is not None and existing.metadata_.get("content_hash") == chunk.content_hash:
        logger.debug("Memory skip unchanged source_id=%s", chunk.source_id)
        return IndexResult(
            memory_id=existing.id,
            action="skipped",
            usage=EmbedUsage(model=settings.openai_embedding_model, input_tokens=0, api_calls=0),
        )

    vectors, usage = await embed_texts([chunk.content], settings)
    memory, action = await upsert_memory_chunk(session, chunk, vectors[0])
    await session.commit()
    logger.info(
        "Memory %s source_id=%s model=%s tokens=%d",
        action,
        chunk.source_id,
        usage.model,
        usage.input_tokens,
    )
    return IndexResult(memory_id=memory.id, action=action, usage=usage)
