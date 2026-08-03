"""Backfill vector memory from existing payment records."""

from __future__ import annotations

import asyncio
import logging
import sys

from assistant.config import get_settings
from assistant.db.session import dispose_db, get_session_factory, init_db
from assistant.memory.wire import format_memory_index_summary, index_all_payment_records

logger = logging.getLogger(__name__)


async def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )

    init_db(settings)
    session_factory = get_session_factory()
    if session_factory is None:
        print("Database session factory not initialized", file=sys.stderr)
        return 1

    summary = await index_all_payment_records(session_factory, settings)
    text = format_memory_index_summary(summary)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))
    await dispose_db()
    if summary.unavailable:
        return 1
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
