"""Verify OpenAI embedding API key (run after filling OPENAI_API_KEY in .env)."""

from __future__ import annotations

import asyncio
import sys

from assistant.config import get_settings
from assistant.memory.embed import embed_texts, format_embed_cost_usd


async def main() -> int:
    settings = get_settings()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY is empty in .env", file=sys.stderr)
        return 1

    print(f"Model: {settings.openai_embedding_model}")
    print("Calling OpenAI embeddings (small test)...")

    vectors, usage = await embed_texts(["Anabella memory smoke test."], settings)
    if not vectors:
        print("No vectors returned", file=sys.stderr)
        return 1

    print(f"OK — dim={len(vectors[0])} tokens={usage.input_tokens} est={format_embed_cost_usd(usage)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
