"""Background scheduled jobs."""

from __future__ import annotations

import logging
from datetime import datetime

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from assistant.config import Settings
from assistant.crypto import SecretBox
from assistant.db.session import get_session_factory
from assistant.ingest.accounts import bootstrap_accounts
from assistant.discord_bot.formatting import (
    format_extraction_failure,
    format_extraction_summary,
    format_payment_record,
)
from assistant.extraction.llm_cost import format_llm_usage_summary
from assistant.extraction.pipeline import process_pending_messages
from assistant.ingest.ics_sync import IcsSyncResult, UpcomingEventSummary, sync_all_calendars
from assistant.ingest.imap_sync import AccountSyncResult, SyncedMessageSummary, sync_all_accounts

logger = logging.getLogger(__name__)

DISCORD_MESSAGE_LIMIT = 2000
MAX_LISTED_MESSAGES = 10


def _truncate(text: str | None, max_len: int = 90) -> str:
    if not text:
        return "(без тема)"
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def _format_received_at(value: datetime | None) -> str:
    if value is None:
        return "?"
    return value.strftime("%d.%m.%Y %H:%M")


def _format_message_line(message: SyncedMessageSummary) -> str:
    sender = message.sender or "неизвестен"
    return (
        f"  • **{_truncate(message.subject)}**\n"
        f"    ↳ `{sender}` · {_format_received_at(message.received_at)}"
    )


def _format_account_section(result: AccountSyncResult) -> list[str]:
    if result.error:
        return [f"- `{result.alias}`: грешка — {result.error[:200]}"]

    lines = [
        f"- `{result.alias}`: {result.inserted} нови / {result.fetched} обработени"
    ]
    if not result.new_messages:
        return lines

    shown = result.new_messages[:MAX_LISTED_MESSAGES]
    lines.extend(_format_message_line(message) for message in shown)
    remaining = len(result.new_messages) - len(shown)
    if remaining > 0:
        lines.append(f"  • … и още **{remaining}**")
    return lines


def _format_event_time(event: UpcomingEventSummary, timezone_name: str) -> str:
    from zoneinfo import ZoneInfo

    local = event.starts_at.astimezone(ZoneInfo(timezone_name))
    if event.all_day:
        return local.strftime("%d.%m.%Y")
    return local.strftime("%d.%m.%Y %H:%M")


def _format_ics_account_section(result: IcsSyncResult, timezone_name: str) -> list[str]:
    if result.error:
        return [f"- `{result.alias}`: грешка — {result.error[:200]}"]

    if result.skipped:
        lines = [f"- `{result.alias}`: без промяна (ETag)"]
    else:
        lines = [
            f"- `{result.alias}`: {result.total_in_window} събития "
            f"({result.upserted} обновени, {result.removed} премахнати)"
        ]

    if not result.upcoming:
        return lines

    lines.append("  **Предстоящи:**")
    for event in result.upcoming[:5]:
        title = _truncate(event.summary, max_len=70)
        when = _format_event_time(event, timezone_name)
        lines.append(f"  • **{title}** · {when}")
    return lines


def _format_ics_summary(results: list[IcsSyncResult], timezone_name: str) -> list[str]:
    if not results:
        return []
    lines = ["**Calendar sync завърши**"]
    for result in results:
        lines.extend(_format_ics_account_section(result, timezone_name))
    return _chunk_discord_messages(lines, fallback="**Calendar sync завърши**")


def _format_sync_summary(results: list[AccountSyncResult]) -> list[str]:
    lines = ["**IMAP sync завърши**"]
    for result in results:
        lines.extend(_format_account_section(result))
    return _chunk_discord_messages(lines, fallback="**IMAP sync завърши**")


def _chunk_discord_messages(lines: list[str], *, fallback: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}".strip() if current else line
        if len(candidate) > DISCORD_MESSAGE_LIMIT - 50 and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [fallback]


async def _notify_channel(
    bot: commands.Bot, channel_id: int, messages: list[str], *, log_label: str
) -> None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.DiscordException:
            logger.warning("Could not resolve %s channel %s", log_label, channel_id)
            return
    if not isinstance(channel, discord.abc.Messageable):
        return

    for message in messages:
        try:
            await channel.send(message)
        except discord.DiscordException:
            logger.exception("Failed to post message to %s channel", log_label)


async def _notify_general(bot: commands.Bot, settings: Settings, messages: list[str]) -> None:
    await _notify_channel(
        bot, settings.discord_channel_general, messages, log_label="#general"
    )


async def _notify_payments(bot: commands.Bot, settings: Settings, messages: list[str]) -> None:
    await _notify_channel(
        bot, settings.discord_channel_payments, messages, log_label="#payments"
    )


async def run_extraction(bot: commands.Bot, settings: Settings) -> None:
    session_factory = get_session_factory()
    if session_factory is None:
        logger.error("Session factory not initialized")
        return

    from sqlalchemy import select

    from assistant.db.models import PaymentRecord

    logger.info("Extraction starting")
    result = await process_pending_messages(session_factory, settings)
    logger.info(
        "Extraction done: processed=%d extracted=%d inserted=%d no_match=%d failed=%d skipped=%d",
        result.processed,
        result.extracted,
        result.inserted_records,
        result.no_match,
        result.failed,
        result.skipped,
    )

    messages: list[str] = []
    if result.processed or result.no_match or result.failed or result.llm_usage.has_usage:
        messages.append(
            format_extraction_summary(
                processed=result.processed,
                extracted=result.extracted,
                skipped=result.skipped,
                no_match=result.no_match,
                failed=result.failed,
                inserted_records=result.inserted_records,
            )
        )

    if result.llm_usage.has_usage:
        messages.append(format_llm_usage_summary(result.llm_usage))

    if result.new_record_ids:
        async with session_factory() as session:
            records = (
                await session.scalars(
                    select(PaymentRecord)
                    .where(PaymentRecord.id.in_(result.new_record_ids))
                    .order_by(PaymentRecord.id.asc())
                )
            ).all()
        for record in records:
            messages.append(format_payment_record(record))

    if result.failures:
        for failure in result.failures[:5]:
            messages.append(format_extraction_failure(failure))
        remaining = len(result.failures) - 5
        if remaining > 0:
            messages.append(f"_… и още **{remaining}** неуспешни извличания_")

    if messages:
        await _notify_payments(bot, settings, _chunk_discord_messages(messages, fallback="**Extraction**"))


async def extraction_job(bot: commands.Bot, settings: Settings) -> None:
    try:
        await run_extraction(bot, settings)
    except Exception:
        logger.exception("Extraction job failed")
        await _notify_payments(
            bot,
            settings,
            ["**Extraction:** неочаквана грешка — виж логовете на сървъра."],
        )


async def run_ics_sync(bot: commands.Bot, settings: Settings, secret_box: SecretBox) -> None:
    session_factory = get_session_factory()
    if session_factory is None:
        logger.error("Session factory not initialized")
        return

    logger.info("ICS sync starting")
    results = await sync_all_calendars(session_factory, settings, secret_box)
    for result in results:
        if result.error:
            logger.error("ICS sync %s failed: %s", result.alias, result.error)
        elif result.skipped:
            logger.info(
                "ICS sync %s: unchanged (ETag), %d upcoming",
                result.alias,
                len(result.upcoming),
            )
        else:
            logger.info(
                "ICS sync %s: upserted=%d removed=%d total=%d upcoming=%d",
                result.alias,
                result.upserted,
                result.removed,
                result.total_in_window,
                len(result.upcoming),
            )
    if results:
        await _notify_general(bot, settings, _format_ics_summary(results, settings.journal_timezone))
    else:
        logger.warning("ICS sync: no accounts with ICS URL configured")


async def ics_sync_job(bot: commands.Bot, settings: Settings, secret_box: SecretBox) -> None:
    try:
        await run_ics_sync(bot, settings, secret_box)
    except Exception:
        logger.exception("Scheduled ICS sync job failed")
        await _notify_general(
            bot,
            settings,
            ["**Calendar sync:** неочаквана грешка — виж логовете на сървъра."],
        )


async def run_imap_sync(bot: commands.Bot, settings: Settings, secret_box: SecretBox) -> None:
    session_factory = get_session_factory()
    if session_factory is None:
        logger.error("Session factory not initialized")
        return

    async with session_factory() as session:
        await bootstrap_accounts(session, settings, secret_box)

    results = await sync_all_accounts(session_factory, settings, secret_box)
    await _notify_general(bot, settings, _format_sync_summary(results))
    await run_extraction(bot, settings)


async def imap_sync_job(bot: commands.Bot, settings: Settings, secret_box: SecretBox) -> None:
    try:
        await run_imap_sync(bot, settings, secret_box)
    except Exception:
        logger.exception("Scheduled IMAP sync job failed")
        await _notify_general(
            bot,
            settings,
            ["**IMAP sync:** неочаквана грешка — виж логовете на сървъра."],
        )


def create_scheduler(
    bot: commands.Bot, settings: Settings, secret_box: SecretBox
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.journal_timezone)
    scheduler.add_job(
        imap_sync_job,
        trigger="interval",
        seconds=settings.imap_sync_interval,
        args=[bot, settings, secret_box],
        id="imap_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        ics_sync_job,
        trigger="interval",
        seconds=settings.ics_sync_interval,
        args=[bot, settings, secret_box],
        id="ics_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Scheduled jobs: imap every %ss, calendar every %ss",
        settings.imap_sync_interval,
        settings.ics_sync_interval,
    )
    return scheduler
