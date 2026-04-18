# kalshi-tradr

Telegram-driven trading bot for the [Kalshi](https://kalshi.com) prediction market exchange.

## Features

- `/scan` – find markets ending in the next 1–3 hours with ≥90% odds on one side.
- `/bet <free text> [amount]` – natural-language bet placement (e.g. `/bet warriors vs lakers 25`). Uses keyword matching against open Kalshi events; up to 3 disambiguation buttons when ambiguous.
- `/status` – account balance, open positions, resting orders.
- Quarter-Kelly auto-sizing when no bet amount is provided (hard-capped by `MAX_BET_USD`).
- Inline `✅ Confirm / ❌ Cancel` prompt before every trade, gated by `BET_CONFIRM_REQUIRED` (default `true`).
- Allow-list on `chat_id` so only approved Telegram chats can control the bot.
- All pending confirmations and placed bets persisted to Postgres.

## Quick start

```bash
# 1. install deps (Python 3.11+)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. configure
cp .env.example .env
# edit .env and drop your Kalshi PEM at ./secrets/kalshi.pem

# 3. create the database
createdb kalshi_tradr

# 4. run tests
pytest -q

# 5. start the bot (long-polls Telegram)
python -m kalshi_tradr.main
```

## Environment

See [`.env.example`](./.env.example) for the full list. Required:

| Var | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From BotFather |
| `TELEGRAM_ALLOWED_CHAT_IDS` | CSV of chat IDs that may command the bot |
| `KALSHI_API_KEY_ID` | Kalshi API key ID |
| `KALSHI_PRIVATE_KEY_PEM_PATH` | Path to the RSA private key PEM |
| `DATABASE_URL` | Postgres DSN, e.g. `postgresql://user:pass@localhost:5432/kalshi_tradr` |

`KALSHI_ENV` defaults to `demo` (paper funds). Flip to `prod` only after smoke-testing.

## How auto-sizing works

`/scan` surfaces markets where one side is quoted ≥ `SCAN_MIN_PROB` (default 0.90). If you tap *Bet* without specifying an amount, the bot sizes the position with Quarter Kelly:

```
edge    = p − (1 − p) / b         # b = (1 − price) / price
stake$  = fraction × bankroll × edge
stake$  = min(stake$, MAX_BET_USD)
```

Because the market price already embeds the "true" probability, we need an edge estimate. The bot uses `p = min(price_cents/100 + EDGE_BUFFER, 0.99)` — a small cushion over the market price — so lopsided trades still get sized. Override with an explicit amount in `/bet` when you disagree with the default heuristic.

## Telegram commands

| Command | Example |
|---|---|
| `/start`, `/help` | – |
| `/scan` | `/scan` |
| `/bet <text> [amount]` | `/bet warriors vs lakers 25` |
| `/status` | `/status` |

## Out of scope (for now)

- WebSocket market data / live fills (REST polling only)
- Auto-scanning / always-on watchlists
- Multi-leg strategies
- Web dashboard
