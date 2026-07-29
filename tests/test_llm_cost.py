"""Tests for LLM cost formatting."""

from assistant.extraction.llm_cost import LlmUsageTotals, format_llm_usage_summary


def test_format_llm_usage_summary():
    usage = LlmUsageTotals(model="claude-haiku-4-5-20251001", input_tokens=1500, output_tokens=300, api_calls=2)
    text = format_llm_usage_summary(usage)
    assert "LLM разход" in text
    assert "API calls: 2" in text
    assert "1,500 in" in text
