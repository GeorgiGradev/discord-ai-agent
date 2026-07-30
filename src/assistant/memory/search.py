"""Similarity search over indexed memories."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assistant.config import Settings
from assistant.db.models import Memory
from assistant.domain.memory import MemoryKind
from assistant.memory.embed import embed_texts

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryHit:
    id: int
    kind: str
    content: str
    metadata: dict
    source_id: str | None
    score: float


async def search_memories(
    session: AsyncSession,
    query: str,
    settings: Settings,
    *,
    kinds: list[MemoryKind] | None = None,
    top_k: int = 8,
    threshold: float | None = None,
    update_last_accessed: bool = True,
) -> list[MemoryHit]:
    """Return memory chunks most similar to the query text."""
    min_score = settings.memory_similarity_threshold if threshold is None else threshold
    vectors, usage = await embed_texts([query.strip()], settings)
    if not vectors:
        return []

    query_vector = vectors[0]
    distance = Memory.embedding.cosine_distance(query_vector)
    score_expr = (1 - distance).label("score")

    stmt = (
        select(Memory, score_expr)
        .where(Memory.embedding.isnot(None))
        .order_by(distance)
        .limit(top_k)
    )
    if kinds:
        stmt = stmt.where(Memory.kind.in_([kind.value for kind in kinds]))

    rows = (await session.execute(stmt)).all()
    hits: list[MemoryHit] = []
    touched_ids: list[int] = []

    for memory, score in rows:
        similarity = float(score)
        if similarity < min_score:
            continue
        hits.append(
            MemoryHit(
                id=memory.id,
                kind=memory.kind,
                content=memory.content,
                metadata=dict(memory.metadata_ or {}),
                source_id=memory.source_id,
                score=similarity,
            )
        )
        touched_ids.append(memory.id)

    if update_last_accessed and touched_ids:
        now = datetime.now(UTC)
        for memory_id in touched_ids:
            row = await session.get(Memory, memory_id)
            if row is not None:
                row.last_accessed_at = now
        await session.flush()

    logger.info(
        "Memory search query=%r hits=%d/%d embed_tokens=%d",
        query[:80],
        len(hits),
        len(rows),
        usage.input_tokens,
    )
    return hits
