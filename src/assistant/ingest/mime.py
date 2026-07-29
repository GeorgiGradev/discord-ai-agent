"""Parse and normalize email MIME content."""

import hashlib
import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class GmailFetchMetadata:
    labels: list[str]
    gm_msgid: str | None
    gm_thrid: str | None


_GMAIL_LABELS_RE = re.compile(r"X-GM-LABELS \(([^)]*)\)")
_GMAIL_MSGID_RE = re.compile(r"X-GM-MSGID (\d+)")
_GMAIL_THRID_RE = re.compile(r"X-GM-THRID (\d+)")


def parse_gmail_fetch_metadata(raw_parts: list[bytes]) -> GmailFetchMetadata:
    """Parse Gmail IMAP FETCH attributes (not present in MIME headers)."""
    combined = b" ".join(raw_parts).decode(errors="replace")
    labels: list[str] = []
    match = _GMAIL_LABELS_RE.search(combined)
    if match:
        labels = [
            label
            for label in match.group(1).split()
            if label and not label.startswith("\\")
        ]
    msgid_match = _GMAIL_MSGID_RE.search(combined)
    thrid_match = _GMAIL_THRID_RE.search(combined)
    return GmailFetchMetadata(
        labels=labels,
        gm_msgid=msgid_match.group(1) if msgid_match else None,
        gm_thrid=thrid_match.group(1) if thrid_match else None,
    )


def merge_gmail_labels(*sources: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for source in sources:
        for label in source:
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(label)
    return merged


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


def resolve_message_identity(
    headers: dict,
    *,
    uid: int,
    uidvalidity: int,
    gm_msgid: str | None = None,
) -> str:
    """Stable dedup key: Gmail msgid when present, else Message-ID, else folder UID."""
    if gm_msgid:
        return str(gm_msgid)[:64]

    gm_msgid_header = header_value(headers, "X-GM-MSGID")
    if gm_msgid_header:
        return str(gm_msgid_header)[:64]

    message_id = header_value(headers, "Message-ID")
    if message_id:
        normalized = message_id.strip().strip("<>")
        if len(normalized) <= 64:
            return normalized
        return hashlib.sha256(normalized.encode()).hexdigest()

    return f"uid:{uidvalidity}:{uid}"
