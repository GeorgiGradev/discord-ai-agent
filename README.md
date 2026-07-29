# Anabella - Discord AI Assistant

Personal Discord bot that ingests **Gmail accounts** (IMAP), syncs **Google Calendar** (secret iCal URL), and posts **verified payment extractions** to private Discord channels - **deterministic parsers first**, **Haiku LLM fallback** when templates miss, plus an **eval harness** to measure hallucination risk.

> Read-only by design: no outbound email, no payments, no calendar writes.

## Screenshots

### IMAP sync → `#general`

New mail from both Gmail accounts, posted after each sync.

![IMAP sync in #general](docs/screenshots/imap-sync.png)

### Calendar + IMAP sync (`/sync all`)

ICS upcoming events and new email summaries in one run.

![Calendar and IMAP sync](docs/screenshots/calendar-and-imap-sync.png)

### Payment extraction → `#payments` (templates, $0)

Deterministic parsers — UBB obligations and Anthropic receipts with evidence quotes.

![Template extraction in #payments](docs/screenshots/payments-templates.png)

### LLM fallback + cost report (Haiku)

When templates miss, Haiku extracts with verbatim validation; batch cost posted to `#payments`.

![LLM extraction and cost report](docs/screenshots/payments-llm-cost.png)

## Why this project

Most “AI assistants” over email fail silently — wrong amounts, invented due dates, confident nonsense. Anabella inverts that:

1. **Gmail labels + sender routing** decide the pipeline (zero LLM cost for known formats).
2. **Template extractors** parse recurring bill formats (UBB utility table, Anthropic receipts).
3. **Haiku fallback** runs only when templates miss — with the same verbatim checks.
4. Every amount carries a **`evidence_quote`** copied exactly from the email body.
5. **`pytest -m eval`** tracks field-level precision/recall on deterministic extractors.

## Architecture (current)

```
Gmail (IMAP) ──► raw_messages (Postgres)
                      │
                      ▼
              extraction cascade
              JSON-LD → templates → Haiku (fallback)
                      │                    │
                      ▼                    └── token usage → cost estimate
              payment_records ──► Discord #payments

Google Calendar (ICS) ──► calendar_events ──► Discord #general
```

| Layer | Status |
|-------|--------|
| Postgres 17 + pgvector, Alembic | ✅ |
| Multi-account IMAP sync (UID cursor, X-GM-MSGID) | ✅ |
| Calendar ICS sync (ETag, RRULE expansion) | ✅ |
| Payment extraction — UBB & Anthropic templates | ✅ |
| Eval harness (`tests/eval/`) | ✅ |
| LLM fallback — Haiku + verbatim validation | ✅ |
| LLM cost report in `#payments` after each batch | ✅ |
| Conference/career events → `#events` | 🔜 B5 |
| Grounded chat + memory (Sonnet + embeddings) | 🔜 C1–C3 |

## Extraction cascade

| Step | When | Cost |
|------|------|------|
| **JSON-LD** | Invoice markup in email | $0 |
| **Templates** | Known senders (UBB, Anthropic receipt format) | $0 |
| **Haiku** | Template matched but failed, or unknown payment email | ~$0.002/email |
| **Failed** | LLM rejected (bad quote) → alert in `#payments` | billed tokens still counted |

After each extraction batch that used Haiku, `#payments` gets a summary like:

```
LLM разход (Haiku): $0.0052
- API calls: 2
- tokens: 3,669 in / 313 out
```

Estimate uses Anthropic list pricing ($1/M input, $5/M output for Haiku 4.5). **Anthropic console** on the `Anabella` API key is the source of truth for billing.

## Quick start (local)

**Prerequisites:** Python 3.11+, Docker Desktop, Discord bot app, Gmail app passwords, [Anthropic API key](https://console.anthropic.com) (for LLM fallback).

```powershell
# 1. Clone and configure
cp .env.example .env   # fill secrets — never commit .env

# 2. Database
docker compose up -d db

# 3. Python environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 4. Migrations
alembic upgrade head

# 5. Verify Anthropic key (optional, ~$0.001)
python scripts/verify_anthropic.py

# 6. Run the bot (must stay running while you use Discord)
python -m assistant.main
```

### Required `.env` keys (minimum)

| Key | Purpose |
|-----|---------|
| `DISCORD_*` | Bot token, guild, channels, your user ID |
| `FERNET_KEY` | Encrypt Gmail passwords & ICS URLs in DB |
| `ACCOUNT_*` | Two Gmail IMAP accounts + labels |
| `DATABASE_URL` | Postgres (local: `@localhost:5432`) |
| `ANTHROPIC_API_KEY` | Haiku fallback extraction |
| `LLM_EXTRACTION_ENABLED` | `true` / `false` — disable LLM without removing key |

`OPENAI_API_KEY` is **not needed yet** (C1 embeddings). Sonnet is for C2 chat.

### Discord commands

| Command | Action |
|---------|--------|
| `/ping` | Health check |
| `/sync` → `imap` | Email sync + extraction |
| `/sync` → `calendar` | ICS sync |
| `/sync` → `extract` | Re-run payment extraction on pending mail |
| `/sync` → `all` | IMAP + calendar |

### How it works without VPS deploy

Discord hosts your server in the cloud. The bot is a **Python process on your machine** that connects **outbound** to Discord’s API. Docker locally only runs **Postgres**. When the bot is stopped, slash commands time out.

## Testing

```powershell
pytest              # unit tests (eval excluded)
pytest -m eval      # extraction quality harness (deterministic only, no API cost)
```

Eval thresholds: `pyproject.toml` → `[tool.assistant.eval]`.

## Project layout

```
src/assistant/
  ingest/              IMAP sync, ICS sync, MIME parsing
  extraction/
    templates/         UBB, Anthropic (deterministic)
    llm_fallback.py    Haiku structured extraction
    llm_cost.py        token usage + USD estimate
    pipeline.py        cascade orchestration
  discord_bot/         client, slash commands
  scheduler/           periodic sync + #payments notify
scripts/
  verify_anthropic.py  one-shot API key check
tests/
  fixtures/emails/     anonymized samples
  eval/                manifest-driven extraction eval
```

## Security

- **Do not commit `.env`** — bot token, Gmail app passwords, calendar secret URLs, Fernet key, API keys.
- Copy `.env.example` only; set `POSTGRES_PASSWORD` locally.
- **`docker-compose.yml` has no embedded passwords** — credentials live only in `.env`.
- Email fixtures are **anonymized** (synthetic names, redacted Stripe links).
- Bot uses a **Discord user ID allowlist**.
- Use a **dedicated Anthropic API key** (`Anabella`) to isolate cost in the console.

If GitGuardian flags old commits with `assistant:assistant` in compose — those were local dev placeholders, not production secrets. Mark resolved; rotate only if a real token was committed (`.env` was never in git).

## Roadmap

- **B5** — Conference/career events → `#events`
- **C1** — Vector memory (OpenAI embeddings)
- **C2** — Grounded Q&A in `#chat` (Sonnet)
- **C3** — Evening journal

## License

Private / all rights reserved unless otherwise noted.
