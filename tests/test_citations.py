"""Tests for citation matching helpers."""

from assistant.extraction.citations import (
    collapse_whitespace,
    find_quote_in_llm_body,
    normalize_homoglyphs,
    normalize_newlines,
    strip_bracket_urls,
)


def test_normalize_newlines_converts_crlf():
    assert normalize_newlines("a\r\nb") == "a\nb"


def test_find_quote_in_llm_body_allows_crlf_mismatch():
    body = "Beyond the Diagram:\r\nHidden Costs\r\n\r\nКога:30.07.26 19:30"
    quote = "Beyond the Diagram:\nHidden Costs\n\nКога:30.07.26 19:30"
    assert find_quote_in_llm_body(quote, body) == quote


def test_find_quote_in_llm_body_allows_whitespace_mismatch_after_colon():
    body = "Beyond the Diagram:\r\nHidden Costs of Cloud Distributed Architectures"
    quote = "Beyond the Diagram: Hidden Costs of Cloud Distributed Architectures"
    assert find_quote_in_llm_body(quote, body) == quote


def test_find_quote_in_llm_body_allows_skipping_bracket_urls_in_body():
    body = (
        "На DEV.BG All in One 2026\n"
        "[https://tracking.example/very-long-link]\n"
        "Александър Алексиев (CTO @ AMPECO) ще разкаже"
    )
    quote = "На DEV.BG All in One 2026\nАлександър Алексиев (CTO @ AMPECO) ще разкаже"
    assert find_quote_in_llm_body(quote, body) == quote


def test_find_quote_in_llm_body_allows_cyrillic_latin_homoglyphs():
    body = "Къде:Оnline Zoom"
    quote = "Къде:Online Zoom"
    assert find_quote_in_llm_body(quote, body) == quote


def test_collapse_whitespace_and_url_helpers():
    assert collapse_whitespace("a\n\n  b") == "a b"
    assert strip_bracket_urls("x [https://a.com] y") == "x  y"
    assert normalize_homoglyphs("Оnline") == "Online"


def test_find_quote_in_llm_body_rejects_missing_text():
    try:
        find_quote_in_llm_body("not in body", "hello")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "not found" in str(exc)


def test_find_quote_in_llm_body_allows_missing_space_before_year():
    body = "На DEV.BG All in One 2026\nLate Bird билет"
    quote = "На DEV.BG All in One2026\nLate Bird билет"
    assert find_quote_in_llm_body(quote, body) == quote


def test_find_quote_in_llm_body_allows_minor_name_typo_with_url_gap():
    body = (
        "На DEV.BG All in One 2026\n"
        "[https://tracking.example/very-long-link]\n"
        'Хари Хараламбиев (Co-Founder @ Soft Skills Pills) ще говори за "слона в стаята"\n'
        "- конфликтите в екипите"
    )
    quote = (
        "На DEV.BG All in One2026\n"
        'Хари Караламбиев (Co-Founder @ Soft Skills Pills) ще говори за "слона в стаята"\n'
        "- конфликтите"
    )
    assert find_quote_in_llm_body(quote, body) == quote
