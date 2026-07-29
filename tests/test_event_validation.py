"""Tests for event validation rules."""

from datetime import date

from assistant.domain.events import AttendanceMode
from assistant.extraction.base import MessageView
from assistant.extraction.events.base import ExtractedConferenceEvent
from assistant.extraction.events.validation import validate_conference_events


def _msg(**kwargs) -> MessageView:
    defaults = {
        "id": 1,
        "account_id": 1,
        "gm_msgid": "x",
        "sender": "events@dev.bg",
        "subject": "DEV.BG",
        "labels": ["DevBG"],
        "received_at": None,
        "text_body": "На DEV.BG All in One 2026. Late Bird билет за €59.",
        "html_body": None,
    }
    defaults.update(kwargs)
    return MessageView(**defaults)


def test_validate_strips_price_when_not_in_quote():
    record = ExtractedConferenceEvent(
        name="DEV.BG All In One 2026",
        starts_on=None,
        ends_on=None,
        location=None,
        attendance_mode=None,
        price_raw="€59",
        price_minor=5900,
        currency="EUR",
        registration_deadline=None,
        cfp_deadline=None,
        evidence_quote="На DEV.BG All in One 2026",
    )
    llm_body = "На DEV.BG All in One 2026. Late Bird билет за €59."

    validated = validate_conference_events(_msg(), [record], llm_body=llm_body)

    assert len(validated) == 1
    assert validated[0].price_raw is None
    assert validated[0].price_minor is None


def test_validate_keeps_price_when_inside_quote():
    record = ExtractedConferenceEvent(
        name="DEV.BG All In One 2026",
        starts_on=date(2026, 9, 1),
        ends_on=None,
        location="Sofia",
        attendance_mode=AttendanceMode.HYBRID,
        price_raw="€59",
        price_minor=5900,
        currency="EUR",
        registration_deadline=None,
        cfp_deadline=None,
        evidence_quote="Late Bird билет за €59",
    )
    llm_body = "Late Bird билет за €59 до края на юли."

    validated = validate_conference_events(_msg(), [record], llm_body=llm_body)

    assert validated[0].price_raw == "€59"
    assert validated[0].price_minor == 5900
