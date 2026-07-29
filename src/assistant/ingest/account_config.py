"""Account definitions loaded from environment."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvAccount:
    alias: str
    email: str
    imap_host: str
    imap_password: str
    sync_labels: list[str]
    ics_url: str | None = None
