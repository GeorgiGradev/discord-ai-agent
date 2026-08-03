"""Vector memory: embed, chunk, index, and search (C1)."""

from assistant.memory.embed import EmbedUsage, embed_texts
from assistant.memory.index import IndexResult, index_payment_record
from assistant.memory.search import MemoryHit, search_memories
from assistant.memory.wire import (
    MemoryIndexSummary,
    format_memory_index_summary,
    index_all_payment_records,
    index_payment_record_ids,
)

__all__ = [
    "EmbedUsage",
    "IndexResult",
    "MemoryHit",
    "MemoryIndexSummary",
    "embed_texts",
    "format_memory_index_summary",
    "index_all_payment_records",
    "index_payment_record",
    "index_payment_record_ids",
    "search_memories",
]
