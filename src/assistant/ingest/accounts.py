"""Bootstrap Gmail accounts from environment into the database."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assistant.config import Settings
from assistant.crypto import SecretBox
from assistant.db.models import Account, IcsSyncState, SyncState
from assistant.ingest.mime import normalize_app_password

ALL_MAIL_FOLDER = "[Gmail]/All Mail"


async def bootstrap_accounts(
    session: AsyncSession, settings: Settings, secret_box: SecretBox
) -> None:
    for env_account in settings.env_accounts():
        encrypted_password = secret_box.encrypt(
            normalize_app_password(env_account.imap_password)
        )
        encrypted_ics = (
            secret_box.encrypt(env_account.ics_url) if env_account.ics_url else None
        )

        account = await session.scalar(
            select(Account).where(Account.alias == env_account.alias)
        )
        if account is None:
            account = Account(
                alias=env_account.alias,
                email=env_account.email,
                imap_host=env_account.imap_host,
                app_password_enc=encrypted_password,
                sync_labels=env_account.sync_labels,
                ics_url_enc=encrypted_ics,
                enabled=True,
            )
            session.add(account)
            await session.flush()
            session.add(
                SyncState(
                    account_id=account.id,
                    folder=ALL_MAIL_FOLDER,
                    uidvalidity=None,
                    last_uid=0,
                )
            )
            if encrypted_ics is not None:
                session.add(IcsSyncState(account_id=account.id))
        else:
            account.email = env_account.email
            account.imap_host = env_account.imap_host
            account.app_password_enc = encrypted_password
            account.sync_labels = env_account.sync_labels
            account.ics_url_enc = encrypted_ics
            account.enabled = True

            sync_state = await session.scalar(
                select(SyncState).where(
                    SyncState.account_id == account.id,
                    SyncState.folder == ALL_MAIL_FOLDER,
                )
            )
            if sync_state is None:
                session.add(
                    SyncState(
                        account_id=account.id,
                        folder=ALL_MAIL_FOLDER,
                        uidvalidity=None,
                        last_uid=0,
                    )
                )

            ics_state = await session.scalar(
                select(IcsSyncState).where(IcsSyncState.account_id == account.id)
            )
            if ics_state is None and encrypted_ics is not None:
                session.add(IcsSyncState(account_id=account.id))

    await session.commit()
