"""Formatters for Telegram messages. All output is plain text (no Markdown parse mode)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

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
    return (
        f"{idx}. [{m.ticker}] {m.title}"
        f"\n    {hit.side.upper()} @ {hit.price_cents}¢  closes in {fmt_time_until(m.close_ts)}"
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


def fmt_status(balance: Balance, positions: list[Position], orders: list[RestingOrder]) -> str:
    parts = [fmt_balance(balance), fmt_positions(positions), fmt_orders(orders)]
    return "\n\n".join(parts)


def fmt_confirm(
    *, market: Market, side: str, count: int, price_cents: int, stake_usd: float, reason: str
) -> str:
    max_payout = count  # each contract pays $1 if it wins
    return (
        f"Confirm bet?\n"
        f"Market: [{market.ticker}] {market.title}\n"
        f"Side:   {side.upper()} @ {price_cents}¢\n"
        f"Size:   {count} contracts  ≈ ${stake_usd:,.2f}\n"
        f"Max payout: ${max_payout:,.2f}\n"
        f"Closes: {fmt_close(market.close_ts)} (in {fmt_time_until(market.close_ts)})\n"
        f"Sizing: {reason}"
    )
