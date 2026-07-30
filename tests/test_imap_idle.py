"""Tests for IMAP IDLE helpers."""

from assistant.ingest.imap_idle import _idle_indicates_new_mail


def test_idle_indicates_new_mail_on_exists():
    assert _idle_indicates_new_mail([b"* 12 EXISTS"]) is True


def test_idle_indicates_new_mail_on_recent():
    assert _idle_indicates_new_mail([b"* 1 RECENT"]) is True


def test_idle_indicates_new_mail_false_on_timeout():
    assert _idle_indicates_new_mail([]) is False
