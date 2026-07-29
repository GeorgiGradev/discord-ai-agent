"""Registered deterministic extractors (B2 templates plug in here)."""

from __future__ import annotations

from assistant.extraction.base import Extractor


from assistant.extraction.templates.anthropic_receipt import AnthropicReceiptExtractor
from assistant.extraction.templates.ubb_bitovi_smetki import UbbBitoviSmetkiExtractor


def get_template_extractors() -> list[Extractor]:
    """Return template extractors in priority order."""
    return [
        UbbBitoviSmetkiExtractor(),
        AnthropicReceiptExtractor(),
    ]
