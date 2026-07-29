"""Verify Anthropic API key (run after filling ANTHROPIC_API_KEY in .env)."""

from __future__ import annotations

import asyncio
import sys

from assistant.config import get_settings
from assistant.extraction.base import MessageView
from assistant.extraction.llm_fallback import extract_with_llm


async def main() -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is empty in .env", file=sys.stderr)
        return 1

    msg = MessageView(
        id=0,
        account_id=1,
        gm_msgid="verify",
        sender="billing@example.com",
        subject="Test receipt",
        labels=["Payment"],
        received_at=None,
        text_body="Receipt from Example Co. Amount paid 1.00 EUR. Receipt #TEST-001.",
        html_body=None,
    )

    print(f"Model: {settings.anthropic_model_haiku}")
    print("Calling Haiku (small test extraction)...")

    records = await extract_with_llm(msg, settings)
    if not records:
        print("OK — API works, but model returned zero records for the test email.")
        return 0

    record = records[0]
    print(f"OK — extracted {record.payee} {record.amount_raw} ({record.record_type.value})")
    print(f"Quote: {record.evidence_quote!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
