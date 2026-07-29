"""Tests for Discord event formatting."""

from assistant.discord_bot.formatting import (
    format_event_extraction_failure,
    _humanize_event_failure,
)
from assistant.extraction.events.pipeline import FailedEventExtraction


def test_humanize_quote_mismatch():
    reason = "evidence quote not found in message body: 'foo'"
    assert "Цитатът" in _humanize_event_failure(reason)


def test_format_event_failure_is_compact():
    text = format_event_extraction_failure(
        FailedEventExtraction(
            message_id=218,
            subject="Talk title",
            sender="events@dev.bg",
            reason="evidence quote not found in message body: 'long quote'",
        )
    )
    assert "❌" in text
    assert "events@dev.bg" not in text
    assert "evidence quote not found" not in text
