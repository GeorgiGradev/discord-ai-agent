"""Parse and normalize email MIME content."""

import hashlib
from email.utils import parseaddr


def normalize_app_password(password: str) -> str:
    return password.replace(" ", "").strip()


def extract_email_address(from_header: str | None) -> str | None:
    if not from_header:
        return None
    _, address = parseaddr(from_header)
    return address or from_header


def parse_gmail_labels(headers: dict) -> list[str]:
    raw = headers.get("X-GM-LABELS") or headers.get("x-gm-labels") or ""
    if isinstance(raw, bytes):
        raw = raw.decode(errors="replace")
    if not raw:
        return []
    cleaned = raw.strip().strip("()")
    return [label for label in cleaned.split() if label and not label.startswith("\\")]


def header_value(headers: dict, name: str) -> str | None:
    value = headers.get(name.lower())
    if value is None:
        return None
    if isinstance(value, tuple):
        value = value[0] if value else None
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def resolve_message_identity(headers: dict, *, uid: int, uidvalidity: int) -> str:
    """Stable dedup key: Gmail msgid when present, else Message-ID, else folder UID."""
    gm_msgid = header_value(headers, "X-GM-MSGID")
    if gm_msgid:
        return str(gm_msgid)[:64]

    message_id = header_value(headers, "Message-ID")
    if message_id:
        normalized = message_id.strip().strip("<>")
        if len(normalized) <= 64:
            return normalized
        return hashlib.sha256(normalized.encode()).hexdigest()

    return f"uid:{uidvalidity}:{uid}"
