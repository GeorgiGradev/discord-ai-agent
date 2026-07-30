"""IMAP IDLE monitoring — sync when new mail arrives instead of fixed polling."""

from __future__ import annotations

import asyncio
import logging

from imap_tools import MailBox
from sqlalchemy import select

from assistant.config import Settings
from assistant.crypto import SecretBox
from assistant.db.models import Account
from assistant.db.session import get_session_factory
from assistant.ingest.accounts import ALL_MAIL_FOLDER
from assistant.scheduler.jobs import run_imap_sync

logger = logging.getLogger(__name__)


def _idle_indicates_new_mail(responses: list[bytes]) -> bool:
    for raw in responses:
        text = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
        upper = text.upper()
        if "EXISTS" in upper or "RECENT" in upper:
            return True
    return False


def wait_for_new_mail(
    *,
    email: str,
    imap_host: str,
    password: str,
    timeout: float,
) -> bool:
    """Block in IMAP IDLE until new mail or timeout. Returns True if mail likely arrived."""
    with MailBox(imap_host).login(email, password) as mailbox:
        mailbox.folder.set(ALL_MAIL_FOLDER)
        responses = mailbox.idle.wait(timeout=timeout)
    return _idle_indicates_new_mail(responses)


async def imap_idle_worker(
    bot,
    settings: Settings,
    secret_box: SecretBox,
    account: Account,
) -> None:
    """Run perpetual IDLE loop for one account; triggers sync on new mail."""
    password = secret_box.decrypt(account.app_password_enc)
    timeout = float(settings.imap_idle_timeout)
    logger.info("IMAP IDLE started for account=%s timeout=%ss", account.alias, timeout)

    while True:
        try:
            has_new = await asyncio.to_thread(
                wait_for_new_mail,
                email=account.email,
                imap_host=account.imap_host,
                password=password,
                timeout=timeout,
            )
            if has_new:
                logger.info("IMAP IDLE detected new mail for account=%s", account.alias)
                await run_imap_sync(bot, settings, secret_box, force_notify=False)
        except asyncio.CancelledError:
            logger.info("IMAP IDLE stopped for account=%s", account.alias)
            raise
        except Exception:
            logger.exception("IMAP IDLE error for account=%s; retrying in 60s", account.alias)
            await asyncio.sleep(60)


async def start_imap_idle_monitors(bot, settings: Settings, secret_box: SecretBox) -> None:
    session_factory = get_session_factory()
    if session_factory is None:
        logger.error("IMAP IDLE: session factory not initialized")
        return

    async with session_factory() as session:
        accounts = (
            await session.scalars(select(Account).where(Account.enabled.is_(True)))
        ).all()

    if not accounts:
        logger.warning("IMAP IDLE: no enabled accounts")
        return

    for account in accounts:
        asyncio.create_task(imap_idle_worker(bot, settings, secret_box, account))
