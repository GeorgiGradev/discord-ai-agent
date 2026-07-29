"""Tests for event extraction (B5)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from assistant.config import Settings
from assistant.domain.events import AttendanceMode, CareerEventType
from assistant.extraction.base import MessageView
from assistant.extraction.events.llm_extract import (
    LlmCareerEvent,
    LlmConferenceEvent,
    LlmEventExtractionPayload,
    extract_events_with_llm,
)
from assistant.extraction.events.pipeline import is_event_candidate


def _msg(**kwargs) -> MessageView:
    defaults = {
        "id": 7,
        "account_id": 1,
        "gm_msgid": "test-event",
        "sender": "newsletter@dev.bg",
        "subject": "DevBG weekly digest",
        "labels": ["DevBG"],
        "received_at": None,
        "text_body": None,
        "html_body": None,
    }
    defaults.update(kwargs)
    return MessageView(**defaults)


def _settings(**overrides) -> Settings:
    from cryptography.fernet import Fernet

    base = {
        "DISCORD_BOT_TOKEN": "token",
        "DISCORD_ALLOWED_USER_IDS": "1",
        "DISCORD_GUILD_ID": "1",
        "DISCORD_CHANNEL_GENERAL": "1",
        "DISCORD_CHANNEL_CHAT": "1",
        "DISCORD_CHANNEL_PAYMENTS": "1",
        "DISCORD_CHANNEL_EVENTS": "1",
        "DISCORD_CHANNEL_JOURNAL": "1",
        "FERNET_KEY": Fernet.generate_key().decode(),
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
        "ACCOUNT_PRIMARY_EMAIL": "a@example.com",
        "ACCOUNT_PRIMARY_IMAP_PASSWORD": "pw",
        "ACCOUNT_PRIMARY_SYNC_LABELS": "Payment,DevBG",
        "ACCOUNT_SECONDARY_EMAIL": "b@example.com",
        "ACCOUNT_SECONDARY_IMAP_PASSWORD": "pw2",
        "ACCOUNT_SECONDARY_SYNC_LABELS": "Payment",
        "ANTHROPIC_API_KEY": "test-key",
        "LLM_EXTRACTION_ENABLED": "true",
    }
    base.update(overrides)
    return Settings(**base)


def test_is_event_candidate_matches_devbg_sender():
    assert is_event_candidate(_msg(labels=[], sender="events@dev.bg")) is True
    assert is_event_candidate(_msg(labels=[], sender="billing@example.com")) is False
    assert is_event_candidate(_msg(labels=["DevBG"])) is True
    assert is_event_candidate(_msg(labels=["Payment"], sender="billing@example.com")) is False
    assert is_event_candidate(_msg(labels=["Udemy"])) is True
    assert is_event_candidate(_msg(labels=["LocalAGI"])) is True


@pytest.mark.asyncio
async def test_extract_events_with_llm_returns_validated_records(monkeypatch):
    body = (
        "DevBG Meetup: Sofia Python Night on 2026-03-15 at Tech Park Sofia. "
        "Registration closes 2026-03-10. Free entry."
    )
    msg = _msg(text_body=body)
    settings = _settings()

    from assistant.extraction.llm_cost import LlmUsage

    payload = LlmEventExtractionPayload(
        conference_events=[
            LlmConferenceEvent(
                name="Sofia Python Night",
                starts_on="2026-03-15",
                location="Tech Park Sofia",
                attendance_mode="IN_PERSON",
                price_raw="Free entry",
                registration_deadline="2026-03-10",
                evidence_quote="Sofia Python Night on 2026-03-15 at Tech Park Sofia. Registration closes 2026-03-10. Free entry.",
            )
        ]
    )
    mock_call = AsyncMock(
        return_value=(
            payload,
            LlmUsage(model="claude-haiku-test", input_tokens=400, output_tokens=90),
        )
    )
    monkeypatch.setattr("assistant.extraction.events.llm_extract._call_anthropic", mock_call)

    events, usage = await extract_events_with_llm(msg, settings)

    assert len(events.conference_events) == 1
    event = events.conference_events[0]
    assert event.name == "Sofia Python Night"
    assert event.starts_on.isoformat() == "2026-03-15"
    assert event.attendance_mode == AttendanceMode.IN_PERSON
    assert event.price_minor == 0
    assert usage.api_calls == 1
    mock_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_events_with_llm_rejects_hallucinated_quote(monkeypatch):
    body = "Meetup on 2026-03-15 in Sofia."
    msg = _msg(text_body=body)
    settings = _settings()

    from assistant.extraction.llm_cost import LlmUsage

    payload = LlmEventExtractionPayload(
        conference_events=[
            LlmConferenceEvent(
                name="Fake Conference",
                starts_on="2026-04-01",
                evidence_quote="Fake Conference on 2026-04-01 in Plovdiv",
            )
        ]
    )
    mock_call = AsyncMock(
        return_value=(
            payload,
            LlmUsage(model="claude-haiku-test", input_tokens=300, output_tokens=80),
        )
    )
    monkeypatch.setattr("assistant.extraction.events.llm_extract._call_anthropic", mock_call)

    from assistant.extraction.validation import ExtractionRejected

    with pytest.raises(ExtractionRejected):
        await extract_events_with_llm(msg, settings)

    assert mock_call.await_count == 2


@pytest.mark.asyncio
async def test_extract_events_with_llm_career_event(monkeypatch):
    body = "Acme Corp is hiring a Senior Python Developer. Apply by 2026-04-30."
    msg = _msg(
        sender="jobs@acme.com",
        labels=["LocalAGI"],
        text_body=body,
    )
    settings = _settings()

    from assistant.extraction.llm_cost import LlmUsage

    payload = LlmEventExtractionPayload(
        career_events=[
            LlmCareerEvent(
                event_type="JOB_POSTING",
                company="Acme Corp",
                position="Senior Python Developer",
                deadline="2026-04-30",
                next_step="Apply via careers page",
                evidence_quote="Acme Corp is hiring a Senior Python Developer. Apply by 2026-04-30.",
            )
        ]
    )
    mock_call = AsyncMock(
        return_value=(
            payload,
            LlmUsage(model="claude-haiku-test", input_tokens=350, output_tokens=70),
        )
    )
    monkeypatch.setattr("assistant.extraction.events.llm_extract._call_anthropic", mock_call)

    events, usage = await extract_events_with_llm(msg, settings)

    assert len(events.career_events) == 1
    career = events.career_events[0]
    assert career.event_type == CareerEventType.JOB_POSTING
    assert career.company == "Acme Corp"
    assert career.deadline.isoformat() == "2026-04-30"
    assert usage.api_calls == 1
