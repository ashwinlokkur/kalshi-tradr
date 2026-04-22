"""Formatters for Telegram messages. All output is plain text (no Markdown parse mode)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..db import PlacedBetRow
from ..kalshi.types import Balance, LopsidedHit, Market, Position, RestingOrder


def fmt_time_until(ts: int) -> str:
    if ts <= 0:
        return "?"
    delta = ts - int(time.time())
    if delta < 0:
        return "closed"
    if delta < 3600:
        return f"{delta // 60}m"
    h = delta // 3600
    m = (delta % 3600) // 60
    return f"{h}h{m:02d}m"


def fmt_close(ts: int) -> str:
    if ts <= 0:
        return "?"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def fmt_hit_line(idx: int, hit: LopsidedHit) -> str:
    m = hit.market
    implied = hit.price_cents
    vol = f"  vol={m.volume:,}" if m.volume else ""
    last = f"  last={m.last_price}¢" if m.last_price else ""
    sub = f"\n    {m.subtitle}" if m.subtitle else ""
    return (
        f"{idx}. [{m.ticker}] {m.title}{sub}"
        f"\n    {hit.side.upper()} @ {hit.price_cents}¢ (implied {implied}%)"
        f"  closes in {fmt_time_until(m.close_ts)}{vol}{last}"
    )


def fmt_scan(hits: list[LopsidedHit]) -> str:
    if not hits:
        return "No markets match the filter right now."
    body = "\n".join(fmt_hit_line(i + 1, h) for i, h in enumerate(hits))
    return f"Lopsided markets closing soon:\n{body}"


def fmt_balance(balance: Balance) -> str:
    return f"Balance: ${balance.balance_usd:,.2f}"


def fmt_positions(positions: list[Position]) -> str:
    if not positions:
        return "No open positions."
    rows = []
    for p in positions:
        exposure_usd = p.market_exposure / 100
        rows.append(f"- {p.ticker}: {p.position:+d} contracts (exposure ${exposure_usd:,.2f})")
    return "Positions:\n" + "\n".join(rows)


def fmt_orders(orders: list[RestingOrder]) -> str:
    if not orders:
        return "No resting orders."
    rows = []
    for o in orders:
        rows.append(
            f"- {o.ticker} {o.action} {o.side.upper()} x{o.remaining_count}/{o.count} "
            f"@ {o.price_cents}¢ ({o.status})"
        )
    return "Resting orders:\n" + "\n".join(rows)


def fmt_recent_bets(bets: list[PlacedBetRow]) -> str:
    if not bets:
        return "No recent bets."
    rows = []
    for b in bets:
        when = b.created_at.strftime("%m-%d %H:%M")
        tail = ""
        if b.status != "submitted":
            tail = f" [{b.status}]"
            if b.error:
                tail += f" {b.error[:60]}"
        rows.append(
            f"- {when}  {b.ticker} {b.side.upper()} x{b.count} @ {b.price_cents}¢  "
            f"${float(b.cost_usd):,.2f}{tail}"
        )
    return "Recent bets (bot-placed):\n" + "\n".join(rows)


def fmt_status(
    balance: Balance,
    positions: list[Position],
    orders: list[RestingOrder],
    recent: list[PlacedBetRow] | None = None,
) -> str:
    parts = [fmt_balance(balance), fmt_positions(positions), fmt_orders(orders)]
    if recent is not None:
        parts.append(fmt_recent_bets(recent))
    return "\n\n".join(parts)


def _implied_pct(price_cents: int | None) -> str:
    if not price_cents:
        return "?"
    return f"{price_cents}%"


def fmt_market_quote(market: Market) -> str:
    """One-line best-quote summary with liquidity context for decision making."""
    yes = f"YES {market.yes_bid or '?'}/{market.yes_ask or '?'}¢"
    no = f"NO {market.no_bid or '?'}/{market.no_ask or '?'}¢"
    vol = f"vol={market.volume:,}" if market.volume else "vol=0"
    last = f"last={market.last_price}¢" if market.last_price else "last=?"
    return f"{yes}  {no}  {last}  {vol}"


def fmt_market_card(market: Market) -> str:
    """Richer multi-line view used when asking the user to pick from an event."""
    lines = [f"[{market.ticker}] {market.title}"]
    if market.subtitle:
        lines.append(f"  {market.subtitle}")
    lines.append(
        f"  {fmt_market_quote(market)}  closes in {fmt_time_until(market.close_ts)}"
    )
    return "\n".join(lines)


def fmt_confirm(
    *, market: Market, side: str, count: int, price_cents: int, stake_usd: float, reason: str
) -> str:
    max_payout = count  # each contract pays $1 if it wins
    implied = _implied_pct(price_cents)
    profit_if_win = max_payout - stake_usd
    return (
        f"Confirm bet?\n"
        f"Market: [{market.ticker}] {market.title}\n"
        + (f"  {market.subtitle}\n" if market.subtitle else "")
        + f"Quote:  {fmt_market_quote(market)}\n"
        f"Side:   {side.upper()} @ {price_cents}¢  (implied {implied})\n"
        f"Size:   {count} contracts  ≈ ${stake_usd:,.2f}\n"
        f"If wins: +${profit_if_win:,.2f}  |  If loses: -${stake_usd:,.2f}\n"
        f"Max payout: ${max_payout:,.2f}\n"
        f"Closes: {fmt_close(market.close_ts)} (in {fmt_time_until(market.close_ts)})\n"
        f"Sizing: {reason}"
    )
