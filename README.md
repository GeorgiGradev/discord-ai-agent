# Anabella — Discord AI Assistant

Personal Discord bot that ingests **two Gmail accounts** (IMAP), syncs **Google Calendar** (secret iCal URL), and posts **verified payment extractions** to private Discord channels - with **deterministic parsers first**, LLM fallback later, and an eval harness to measure hallucination risk.

> Read-only by design: no outbound email, no payments, no calendar writes.

## Why this project

Most “AI assistants” over email fail silently — wrong amounts, invented due dates, confident nonsense. Anabella inverts that:

1. **Gmail labels + sender routing** decide the pipeline (zero LLM cost).
2. **Template extractors** parse recurring bill formats (UBB utility table, Anthropic receipts).
3. Every amount carries a **verbatim `evidence_quote`** checked against the raw message body.
4. **`pytest -m eval`** tracks field-level precision/recall before any LLM layer ships.

## Architecture (current)

```
Gmail (IMAP) ──► raw_messages (Postgres)
                      │
                      ▼
              extraction cascade
              JSON-LD → templates → (LLM later)
                      │
                      ▼
              payment_records ──► Discord #payments

Google Calendar (ICS) ──► calendar_events ──► Discord #general
```

| Layer | Status |
|-------|--------|
| Postgres 17 + pgvector, Alembic | ✅ |
| Multi-account IMAP sync (UID cursor, X-GM-MSGID) | ✅ |
| Calendar ICS sync (ETag, RRULE expansion) | ✅ |
| Payment extraction (UBB, Anthropic templates) | ✅ |
| Eval harness (`tests/eval/`) | ✅ |
| LLM fallback extraction (Haiku + verbatim validation) | ✅ |
| Conference/career events → `#events` | 🔜 B5 |
| Grounded chat + memory | 🔜 C1–C3 |

## Quick start (local)

**Prerequisites:** Python 3.11+, Docker Desktop, a Discord bot application, Gmail app passwords.

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

# 5. Run the bot (must stay running while you use Discord)
python -m assistant.main
```

In Discord: `/ping` → `pong`, `/sync` → force IMAP / calendar / extraction.

### How it works without VPS deploy

Discord hosts your server in the cloud. The bot is a **Python process on your machine** that connects **outbound** to Discord’s API (like a chat client). Docker locally only runs **Postgres**. When your laptop is off or the bot is stopped, slash commands time out.

## Testing

```powershell
pytest              # unit tests (eval excluded)
pytest -m eval      # extraction quality harness
```

Eval thresholds live in `pyproject.toml` under `[tool.assistant.eval]`.

## Project layout

```
src/assistant/
  ingest/          IMAP sync, ICS sync, MIME parsing
  extraction/      cascade, templates, validation
  domain/          payment types, money helpers
  discord_bot/     client, slash commands
  scheduler/       periodic sync jobs
tests/
  fixtures/emails/ anonymized real-format samples
  eval/            manifest-driven extraction eval
```

## Security

- **Do not commit `.env`** — it contains bot token, Gmail app passwords, calendar secret URLs, and Fernet key.
- Copy `.env.example` only; fill `POSTGRES_PASSWORD` and build `DATABASE_URL` locally.
- **`docker-compose.yml` has no embedded passwords** — Postgres credentials live only in `.env`.
- Email fixtures are **anonymized** (synthetic names, redacted Stripe links).
- Bot uses a **Discord user ID allowlist** — only configured users can run commands.

If GitGuardian flags old commits: early versions had local dev defaults like `assistant:assistant` in compose — not production secrets. After the fix, mark the incident resolved in GitGuardian; no rotation needed unless a real token was committed (`.env` was never in git).

## Roadmap

- **B5** — Conference/career events → `#events`
- **C1–C3** — Vector memory, grounded Q&A, evening journal

## License

Private / all rights reserved unless otherwise noted. Add an open-source license before making the repository public if you want others to reuse the code.
