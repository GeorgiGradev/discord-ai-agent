"""IMAP synchronization for Gmail accounts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from imap_tools import AND, OR, A, MailBox, U
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.config import Settings
from assistant.crypto import SecretBox
from assistant.db.models import Account, RawMessage, SyncState
from assistant.ingest.accounts import ALL_MAIL_FOLDER
from assistant.ingest.mime import (
    extract_email_address,
    header_value,
    parse_gmail_labels,
    resolve_message_identity,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchedMessage:
    gm_msgid: str
    thread_id: str | None
    sender: str | None
    subject: str | None
    labels: list[str]
    received_at: datetime | None
    text_body: str | None
    html_body: str | None
    uid: int


@dataclass(frozen=True)
class SyncedMessageSummary:
    sender: str | None
    subject: str | None
    received_at: datetime | None


@dataclass(frozen=True)
class AccountSyncResult:
    alias: str
    fetched: int
    inserted: int
    new_messages: list[SyncedMessageSummary]
    error: str | None = None


def _label_criteria(labels: list[str], since: date) -> AND | OR:
    label_filters = OR(*[A(gmail_label=label) for label in labels])
    return AND(label_filters, A(sent_date_gte=since))


def _to_fetched_message(msg, uidvalidity: int) -> FetchedMessage | None:
    labels = parse_gmail_labels(msg.headers)
    received_at = msg.date
    if received_at and received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)

    return FetchedMessage(
        gm_msgid=resolve_message_identity(
            msg.headers, uid=int(msg.uid), uidvalidity=uidvalidity
        ),
        thread_id=header_value(msg.headers, "X-GM-THRID"),
        sender=extract_email_address(msg.from_),
        subject=msg.subject,
        labels=labels,
        received_at=received_at,
        text_body=msg.text,
        html_body=msg.html,
        uid=int(msg.uid),
    )


def _fetch_backfill(
    mailbox: MailBox, labels: list[str], since: date, uidvalidity: int
) -> tuple[list[FetchedMessage], int]:
    criteria = _label_criteria(labels, since)
    seen_uids: set[int] = set()
    fetched: list[FetchedMessage] = []
    max_uid = 0

    for msg in mailbox.fetch(criteria, mark_seen=False, bulk=True):
        uid = int(msg.uid)
        max_uid = max(max_uid, uid)
        if uid in seen_uids:
            continue
        seen_uids.add(uid)
        parsed = _to_fetched_message(msg, uidvalidity)
        if parsed is not None:
            fetched.append(parsed)

    return fetched, max_uid


def _fetch_incremental(
    mailbox: MailBox, labels: list[str], last_uid: int, uidvalidity: int
) -> tuple[list[FetchedMessage], int]:
    criteria = AND(
        OR(*[A(gmail_label=label) for label in labels]),
        A(uid=U(str(last_uid + 1), "*")),
    )
    fetched: list[FetchedMessage] = []
    max_uid = last_uid

    for msg in mailbox.fetch(criteria, mark_seen=False, bulk=True):
        uid = int(msg.uid)
        max_uid = max(max_uid, uid)
        parsed = _to_fetched_message(msg, uidvalidity)
        if parsed is not None:
            fetched.append(parsed)

    return fetched, max_uid


def _sync_account_imap(
    *,
    email: str,
    imap_host: str,
    password: str,
    labels: list[str],
    last_uid: int,
    uidvalidity: int | None,
    backfill_days: int,
) -> tuple[list[FetchedMessage], int, int]:
    """Returns fetched messages, new uidvalidity, new last_uid."""
    with MailBox(imap_host).login(email, password) as mailbox:
        mailbox.folder.set(ALL_MAIL_FOLDER)
        status = mailbox.folder.status(None)
        current_uidvalidity = int(status["UIDVALIDITY"])

        reset_cursor = uidvalidity is not None and uidvalidity != current_uidvalidity
        effective_last_uid = 0 if reset_cursor else last_uid

        if effective_last_uid == 0:
            since = date.today() - timedelta(days=backfill_days)
            messages, scan_max_uid = _fetch_backfill(
                mailbox, labels, since, current_uidvalidity
            )
            new_last_uid = scan_max_uid if scan_max_uid > 0 else effective_last_uid
        else:
            messages, scan_max_uid = _fetch_incremental(
                mailbox, labels, effective_last_uid, current_uidvalidity
            )
            new_last_uid = max(scan_max_uid, effective_last_uid)

        return messages, current_uidvalidity, new_last_uid


def fetch_account_messages(
    account: Account,
    password: str,
    sync_state: SyncState,
    backfill_days: int,
) -> tuple[list[FetchedMessage], int, int]:
    return _sync_account_imap(
        email=account.email,
        imap_host=account.imap_host,
        password=password,
        labels=list(account.sync_labels or []),
        last_uid=int(sync_state.last_uid),
        uidvalidity=sync_state.uidvalidity,
        backfill_days=backfill_days,
    )


async def _persist_messages(
    session: AsyncSession, account_id: int, messages: list[FetchedMessage]
) -> list[SyncedMessageSummary]:
    inserted: list[SyncedMessageSummary] = []
    for message in messages:
        stmt = (
            insert(RawMessage)
            .values(
                account_id=account_id,
                gm_msgid=message.gm_msgid,
                thread_id=message.thread_id,
                sender=message.sender,
                subject=message.subject,
                labels=message.labels,
                received_at=message.received_at,
                text_body=message.text_body,
                html_body=message.html_body,
                extraction_status="pending",
            )
            .on_conflict_do_nothing(constraint="uq_raw_messages_account_gm_msgid")
            .returning(RawMessage.id)
        )
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            inserted.append(
                SyncedMessageSummary(
                    sender=message.sender,
                    subject=message.subject,
                    received_at=message.received_at,
                )
            )
    return inserted


async def sync_all_accounts(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    secret_box: SecretBox,
) -> list[AccountSyncResult]:
    import asyncio

    results: list[AccountSyncResult] = []

    async with session_factory() as session:
        accounts = (
            await session.scalars(select(Account).where(Account.enabled.is_(True)))
        ).all()

    for account in accounts:
        async with session_factory() as session:
            sync_state = await session.scalar(
                select(SyncState).where(
                    SyncState.account_id == account.id,
                    SyncState.folder == ALL_MAIL_FOLDER,
                )
            )
            if sync_state is None:
                results.append(
                    AccountSyncResult(
                        alias=account.alias,
                        fetched=0,
                        inserted=0,
                        new_messages=[],
                        error="missing sync_state",
                    )
                )
                continue

            try:
                password = secret_box.decrypt(account.app_password_enc)
                messages, uidvalidity, last_uid = await asyncio.to_thread(
                    fetch_account_messages,
                    account,
                    password,
                    sync_state,
                    settings.imap_backfill_days,
                )
                new_messages = await _persist_messages(session, account.id, messages)
                sync_state.uidvalidity = uidvalidity
                sync_state.last_uid = last_uid
                await session.commit()
                results.append(
                    AccountSyncResult(
                        alias=account.alias,
                        fetched=len(messages),
                        inserted=len(new_messages),
                        new_messages=new_messages,
                    )
                )
                logger.info(
                    "IMAP sync %s: fetched=%d inserted=%d last_uid=%d",
                    account.alias,
                    len(messages),
                    len(new_messages),
                    last_uid,
                )
            except Exception as exc:
                await session.rollback()
                logger.exception("IMAP sync failed for %s", account.alias)
                results.append(
                    AccountSyncResult(
                        alias=account.alias,
                        fetched=0,
                        inserted=0,
                        new_messages=[],
                        error=str(exc),
                    )
                )

    return results
