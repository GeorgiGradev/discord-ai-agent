"""Application entry point."""

import asyncio
import logging
import sys

from assistant.config import get_settings
from assistant.crypto import SecretBox
from assistant.db.session import check_db_connection, dispose_db, get_session_factory, init_db
from assistant.discord_bot.client import create_bot
from assistant.ingest.accounts import bootstrap_accounts
from assistant.scheduler.jobs import create_scheduler


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    init_db(settings)
    secret_box = SecretBox(settings.fernet_key)

    if await check_db_connection():
        logging.getLogger(__name__).info("Database connection OK")
        session_factory = get_session_factory()
        if session_factory is not None:
            async with session_factory() as session:
                await bootstrap_accounts(session, settings, secret_box)
    else:
        logging.getLogger(__name__).warning(
            "Database not reachable — start Postgres with: docker compose up -d db"
        )

    bot = create_bot(settings, secret_box)
    bot.scheduler = create_scheduler(bot, settings, secret_box)

    try:
        await bot.start(settings.discord_bot_token)
    finally:
        if bot.scheduler is not None and bot.scheduler.running:
            bot.scheduler.shutdown(wait=False)
        await dispose_db()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
