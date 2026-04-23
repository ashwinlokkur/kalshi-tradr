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

### Option A — Docker Compose (bundled Postgres)

```bash
# 1. configure
cp .env.example .env
# edit .env (TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_CHAT_IDS, KALSHI_API_KEY_ID)
# DATABASE_URL is overridden by compose, so leave it blank or as-is.
# drop your Kalshi PEM at ./secrets/kalshi.pem

# 2. build + run
docker compose up --build

# logs: docker compose logs -f bot
# psql into the bundled db:  psql postgresql://kalshi:kalshi@localhost:5432/kalshi_tradr
```

### Option B — Local Python (bring your own Postgres)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and drop your Kalshi PEM at ./secrets/kalshi.pem
createdb kalshi_tradr
pytest -q
python -m kalshi_tradr.main
```

### Option C — Local Kubernetes (kind / k3d / minikube / Docker Desktop)

Kustomize manifests live in [`k8s/`](./k8s) with their own [README](./k8s/README.md). TL;DR:

```bash
docker build -t kalshi-tradr:local .
kind load docker-image kalshi-tradr:local         # or k3d/minikube equivalent

kubectl create namespace kalshi-tradr --dry-run=client -o yaml | kubectl apply -f -
kubectl -n kalshi-tradr create secret generic kalshi-tradr-secrets \
  --from-literal=TELEGRAM_BOT_TOKEN='…' \
  --from-literal=TELEGRAM_ALLOWED_CHAT_IDS='11111111,22222222' \
  --from-literal=KALSHI_API_KEY_ID='…' \
  --from-literal=POSTGRES_USER='kalshi' \
  --from-literal=POSTGRES_PASSWORD='kalshi' \
  --from-literal=POSTGRES_DB='kalshi_tradr' \
  --from-literal=DATABASE_URL='postgresql://kalshi:kalshi@postgres:5432/kalshi_tradr' \
  --from-file=kalshi.pem=./secrets/kalshi.pem

kubectl apply -k k8s/
kubectl -n kalshi-tradr logs -f deploy/bot
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
