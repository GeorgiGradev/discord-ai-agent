"""Tests for Gmail MIME helpers."""

from assistant.ingest.mime import parse_gmail_fetch_metadata


def test_parse_gmail_fetch_metadata_extracts_labels_and_ids():
    raw = [
        b'123 (UID 123 FLAGS (\\Seen) X-GM-LABELS (DevBG Payment) '
        b'X-GM-MSGID 987654321 X-GM-THRID 111222333 RFC822.SIZE 4096)',
    ]
    metadata = parse_gmail_fetch_metadata(raw)
    assert metadata.labels == ["DevBG", "Payment"]
    assert metadata.gm_msgid == "987654321"
    assert metadata.gm_thrid == "111222333"
