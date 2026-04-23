# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`kalshi-tradr` is a Telegram-driven trading bot for the Kalshi prediction market exchange. The bot listens for slash commands in allow-listed Telegram chats, talks to Kalshi's v2 REST API with RSA-PSS signed requests, and persists pending/placed bets to Postgres. There is no web UI, no WebSocket feed, and no background scanner — every Kalshi call is triggered by a user command.

## Common commands

All Python commands assume the repo's virtualenv at `.venv/`. If it isn't there, create one with `python -m venv .venv && .venv/bin/pip install -r requirements.txt`.

```bash
# Run the full test suite
.venv/bin/python -m pytest -q

# Run a single test file / test case
.venv/bin/python -m pytest tests/test_matcher.py -q
.venv/bin/python -m pytest tests/test_matcher.py::test_parse_ticker_or_url_full_url -q

# Lint
.venv/bin/python -m ruff check .

# Run the bot locally (needs a populated .env and secrets/kalshi.pem)
.venv/bin/python -m kalshi_tradr.main

# Rebuild + restart the Docker image (bundled Postgres)
docker compose build bot && docker compose up -d bot
docker compose logs -f bot

# Redeploy to the local Kubernetes cluster after changes
docker build -t kalshi-tradr:local .
kind load docker-image kalshi-tradr:local     # or k3d/minikube equivalent
kubectl -n kalshi-tradr rollout restart deploy/bot
kubectl -n kalshi-tradr logs -f deploy/bot
```

Pytest config lives in `pyproject.toml`: `pythonpath=["src"]` and `asyncio_mode=auto` (async tests don't need the `@pytest.mark.asyncio` decorator).

## Architecture

The process is a single asyncio loop (`main.py`) that wires four long-lived components and runs Telegram long-polling until SIGINT/SIGTERM:

1. **`config.Settings`** (pydantic-settings) — reads `.env`, validates chat IDs, derives the Kalshi base URL from `KALSHI_ENV=demo|prod`. `read_private_key()` returns the PEM contents used for request signing.
2. **`db.Database`** — `asyncpg` pool. `connect()` bootstraps the `pending_bets` and `placed_bets` tables via `CREATE TABLE IF NOT EXISTS` (see `db.py::SCHEMA`). There are no migrations; schema changes go into `SCHEMA`.
3. **`kalshi.client.KalshiAsyncClient`** — a hand-rolled `httpx` wrapper. **Do not switch to the `kalshi-python` SDK** — this client exists because Kalshi's request signing (`timestamp_ms + METHOD + path` signed with RSA-PSS) is trivial enough to do directly, and going direct lets us control pagination, retries, and caching.
4. **`telegram_bot.bot.build_application`** — registers `CommandHandler`s and a single `CallbackQueryHandler`. Handlers receive a `Deps` dataclass (`settings`, `db`, `kalshi`) through `application.bot_data["deps"]`.

### Kalshi response-shape compatibility

Kalshi has been migrating its portfolio endpoints from integer-cents fields (`position`, `market_exposure`, `realized_pnl`) to string-dollar fields with a `_dollars` suffix (`position_fp`, `market_exposure_dollars`, …). The client **must read both forms**, preferring the integer when present. Helpers `_parse_position` and `_cents_from_row` in `kalshi/client.py` do this — reuse them for any new portfolio field. `Position.position` is `float` (not `int`) because `position_fp` can be fractional.

### Matcher / series routing

`strategy/matcher.py` is the natural-language-to-market pipeline used by `/bet` and `/search`:

- `tokenize()` strips stopwords and expands a small alias dict (`gsw → {warriors, golden, state, nba, basketball}`). Aliases intentionally tag the sport/league so series-routing can fire without the user naming the league.
- `_gather_events()` first calls `/series`, picks up to 5 series whose title/category/tags overlap the tokens, then fetches `/events?series_ticker=…` only for those. If no series match, it falls back to a broad `/events?status=open` fetch (up to 30 pages of 200 events). This is the main cost lever — prefer extending the alias dict before widening fetch limits.
- `find_candidates()` also re-hydrates events that arrived with empty nested markets by calling `/markets?event_ticker=…`, which is a known `/events` quirk.
- `parse_ticker_or_url()` recognises both bare Kalshi tickers (`^[A-Z0-9]+(?:[-_][A-Z0-9]+)+$`) and `kalshi.com` URLs, so `/bet` can short-circuit the keyword matcher when the user pastes an exact identifier.

### Bet-confirmation flow

`/bet` never places directly. It:

1. Resolves the target market (ticker/URL path first, then keyword matcher with up to 3 disambiguation buttons via `callback_data="pick:<ticker>:<amount>"`).
2. Calls `_propose_bet`, which inserts a row into `pending_bets` (UUID PK, 5-minute `expires_at` TTL) and sends the user a Confirm/Cancel inline keyboard (`callback_data="confirm:<uuid>"` / `"cancel:<uuid>"`).
3. On Confirm, `db.take_pending_bet()` atomically deletes+returns the row (expiry + chat-id-ownership enforced in the SQL), the client submits `/portfolio/orders`, and the outcome is written to `placed_bets`.

If `BET_CONFIRM_REQUIRED=false`, step 3 runs immediately after step 2. `callback_data` is capped at 64 bytes by Telegram, so keep callback formats terse (`kind:arg1:arg2`).

### Sizing

`strategy/sizing.py` implements Quarter Kelly on a binary contract that pays $1: `edge = p - (1-p)/b` where `b = (1-price)/price`. Because the market price already embeds the consensus probability, the bot uses `p = min(price/100 + EDGE_BUFFER, 0.99)` so lopsided trades still size positively. `size_from_explicit_usd` is used when the user passes an amount on `/bet`; `size_bet` is the Kelly path. Both always return ≥1 contract when the stake is positive.

### Security model

Every command handler calls `_authorized(update, settings)` first — the bot rejects any `chat_id` not in `TELEGRAM_ALLOWED_CHAT_IDS`. The allow-list is the only authn/authz; there's no per-user role system. The Kalshi API key, PEM, and DB password live in env vars (or a Kubernetes Secret in the k8s/ manifests).

### Out of scope

No WebSocket market data, no always-on scanner loop, no multi-leg strategies, no web dashboard. Keep additions command-driven and request/response-shaped unless the user explicitly asks to broaden this.
