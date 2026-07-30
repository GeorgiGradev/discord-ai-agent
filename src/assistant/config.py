"""Application configuration from environment variables."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    discord_bot_token: str = Field(alias="DISCORD_BOT_TOKEN")
    discord_allowed_user_ids: list[int] = Field(alias="DISCORD_ALLOWED_USER_IDS")
    discord_guild_id: int = Field(alias="DISCORD_GUILD_ID")
    discord_channel_general: int = Field(alias="DISCORD_CHANNEL_GENERAL")
    discord_channel_chat: int = Field(alias="DISCORD_CHANNEL_CHAT")
    discord_channel_payments: int = Field(alias="DISCORD_CHANNEL_PAYMENTS")
    discord_channel_events: int = Field(alias="DISCORD_CHANNEL_EVENTS")
    discord_channel_journal: int = Field(alias="DISCORD_CHANNEL_JOURNAL")

    fernet_key: str = Field(alias="FERNET_KEY")
    database_url: str = Field(alias="DATABASE_URL")

    imap_sync_interval: int = Field(default=300, alias="IMAP_SYNC_INTERVAL")
    imap_idle_timeout: int = Field(default=300, alias="IMAP_IDLE_TIMEOUT")
    ics_sync_interval: int = Field(default=900, alias="ICS_SYNC_INTERVAL")
    ics_sync_hour: int = Field(default=8, alias="ICS_SYNC_HOUR")
    ics_sync_minute: int = Field(default=0, alias="ICS_SYNC_MINUTE")

    journal_hour: int = Field(default=20, alias="JOURNAL_HOUR")
    journal_minute: int = Field(default=0, alias="JOURNAL_MINUTE")
    journal_timezone: str = Field(default="Europe/Sofia", alias="JOURNAL_TIMEZONE")

    memory_similarity_threshold: float = Field(
        default=0.35, alias="MEMORY_SIMILARITY_THRESHOLD"
    )
    memory_embed_batch_size: int = Field(default=32, alias="MEMORY_EMBED_BATCH_SIZE")
    citation_max_retries: int = Field(default=1, alias="CITATION_MAX_RETRIES")
    llm_extraction_enabled: bool = Field(default=True, alias="LLM_EXTRACTION_ENABLED")
    event_extraction_batch_size: int = Field(default=5, alias="EVENT_EXTRACTION_BATCH_SIZE")

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model_haiku: str = Field(
        default="claude-haiku-4-5-20251001", alias="ANTHROPIC_MODEL_HAIKU"
    )
    anthropic_model_sonnet: str = Field(
        default="claude-sonnet-4-20250514", alias="ANTHROPIC_MODEL_SONNET"
    )
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )

    account_primary_alias: str = Field(default="primary", alias="ACCOUNT_PRIMARY_ALIAS")
    account_primary_email: str = Field(alias="ACCOUNT_PRIMARY_EMAIL")
    account_primary_imap_host: str = Field(
        default="imap.gmail.com", alias="ACCOUNT_PRIMARY_IMAP_HOST"
    )
    account_primary_imap_password: str = Field(alias="ACCOUNT_PRIMARY_IMAP_PASSWORD")
    account_primary_sync_labels: str = Field(alias="ACCOUNT_PRIMARY_SYNC_LABELS")
    account_primary_ics_url: str | None = Field(default=None, alias="ACCOUNT_PRIMARY_ICS_URL")

    account_secondary_alias: str = Field(default="secondary", alias="ACCOUNT_SECONDARY_ALIAS")
    account_secondary_email: str = Field(alias="ACCOUNT_SECONDARY_EMAIL")
    account_secondary_imap_host: str = Field(
        default="imap.gmail.com", alias="ACCOUNT_SECONDARY_IMAP_HOST"
    )
    account_secondary_imap_password: str = Field(alias="ACCOUNT_SECONDARY_IMAP_PASSWORD")
    account_secondary_sync_labels: str = Field(alias="ACCOUNT_SECONDARY_SYNC_LABELS")
    account_secondary_ics_url: str | None = Field(
        default=None, alias="ACCOUNT_SECONDARY_ICS_URL"
    )

    imap_backfill_days: int = Field(default=365, alias="IMAP_BACKFILL_DAYS")
    ics_horizon_days_past: int = Field(default=30, alias="ICS_HORIZON_DAYS_PAST")
    ics_horizon_days_future: int = Field(default=365, alias="ICS_HORIZON_DAYS_FUTURE")

    @staticmethod
    def parse_label_list(value: str) -> list[str]:
        return [part.strip() for part in value.split(",") if part.strip()]

    def env_accounts(self) -> list["EnvAccount"]:
        from assistant.ingest.account_config import EnvAccount

        return [
            EnvAccount(
                alias=self.account_primary_alias,
                email=self.account_primary_email,
                imap_host=self.account_primary_imap_host,
                imap_password=self.account_primary_imap_password,
                sync_labels=self.parse_label_list(self.account_primary_sync_labels),
                ics_url=self.account_primary_ics_url,
            ),
            EnvAccount(
                alias=self.account_secondary_alias,
                email=self.account_secondary_email,
                imap_host=self.account_secondary_imap_host,
                imap_password=self.account_secondary_imap_password,
                sync_labels=self.parse_label_list(self.account_secondary_sync_labels),
                ics_url=self.account_secondary_ics_url,
            ),
        ]

    @field_validator("discord_allowed_user_ids", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, value: object) -> list[int]:
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            return [int(item) for item in value]
        raise ValueError("DISCORD_ALLOWED_USER_IDS must be an int or comma-separated list")

    def is_user_allowed(self, user_id: int) -> bool:
        return user_id in self.discord_allowed_user_ids


@lru_cache
def get_settings() -> Settings:
    return Settings()
