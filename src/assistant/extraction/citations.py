"""Shared verbatim citation checks for LLM extraction."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_BRACKET_URL_RE = re.compile(r"\[https?://[^\]]+\]")
_YEAR_SPACE_RE = re.compile(r"(\S)\s+(\d{4}\b)")

# Common Cyrillic/Latin lookalikes in Bulgarian marketing emails (e.g. "Оnline").
_CYRILLIC_LATIN_HOMOGLYPHS = str.maketrans(
    "АВСЕКМНОРТХУабвекмнортху",
    "ABCEKMNORTXYabvekmnortxy",
)

_FUZZY_TOKEN_MIN_LEN = 5
_FUZZY_TOKEN_RATIO = 0.88


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_newlines(text)).strip()


def strip_bracket_urls(text: str) -> str:
    return _BRACKET_URL_RE.sub("", text)


def normalize_homoglyphs(text: str) -> str:
    return text.translate(_CYRILLIC_LATIN_HOMOGLYPHS)


def normalize_optional_year_space(text: str) -> str:
    """Treat 'One 2026' and 'One2026' as equivalent for matching."""
    return _YEAR_SPACE_RE.sub(r"\1\2", text)


def _normalize_for_match(text: str, *, strip_urls: bool, homoglyphs: bool) -> str:
    normalized = text
    if strip_urls:
        normalized = strip_bracket_urls(normalized)
    normalized = collapse_whitespace(normalized)
    normalized = normalize_optional_year_space(normalized)
    if homoglyphs:
        normalized = normalize_homoglyphs(normalized)
    return normalized


def _tokenize_for_match(text: str) -> list[str]:
    return _normalize_for_match(text, strip_urls=True, homoglyphs=True).split()


def _token_matches(needle: str, candidate: str) -> bool:
    if needle == candidate:
        return True
    if len(needle) < _FUZZY_TOKEN_MIN_LEN or len(candidate) < _FUZZY_TOKEN_MIN_LEN:
        return False
    return SequenceMatcher(None, needle, candidate).ratio() >= _FUZZY_TOKEN_RATIO


def _fuzzy_tokens_in_order(needle: str, haystack: str) -> bool:
    """Match when LLM slightly garbles spacing or a name spelling."""
    needle_tokens = _tokenize_for_match(needle)
    body_tokens = _tokenize_for_match(haystack)
    if not needle_tokens or not body_tokens:
        return False

    significant = [token for token in needle_tokens if len(token) > 2]
    if len(significant) < 4:
        return False

    body_idx = 0
    for token in needle_tokens:
        if len(token) <= 2:
            continue
        found = False
        while body_idx < len(body_tokens):
            candidate = body_tokens[body_idx]
            body_idx += 1
            if _token_matches(token, candidate):
                found = True
                break
        if not found:
            return False
    return True


def find_quote_in_llm_body(needle: str, llm_body: str) -> str:
    """Match evidence quotes against the same body text sent to the LLM."""
    if not needle:
        raise ValueError("empty evidence quote")
    if not llm_body:
        raise ValueError("empty llm body")

    normalized_needle = normalize_newlines(needle.strip())
    normalized_body = normalize_newlines(llm_body)

    attempts = [
        (normalized_needle, normalized_body),
        (
            _normalize_for_match(normalized_needle, strip_urls=False, homoglyphs=False),
            _normalize_for_match(normalized_body, strip_urls=False, homoglyphs=False),
        ),
        (
            _normalize_for_match(normalized_needle, strip_urls=False, homoglyphs=True),
            _normalize_for_match(normalized_body, strip_urls=False, homoglyphs=True),
        ),
        (
            _normalize_for_match(normalized_needle, strip_urls=True, homoglyphs=False),
            _normalize_for_match(normalized_body, strip_urls=True, homoglyphs=False),
        ),
        (
            _normalize_for_match(normalized_needle, strip_urls=True, homoglyphs=True),
            _normalize_for_match(normalized_body, strip_urls=True, homoglyphs=True),
        ),
    ]
    for tier_needle, tier_body in attempts:
        if tier_needle in tier_body:
            return needle

    if _fuzzy_tokens_in_order(normalized_needle, normalized_body):
        return needle

    raise ValueError(
        f"evidence quote not found in message body: {needle[:120]!r}"
        + ("…" if len(needle) > 120 else "")
    )
