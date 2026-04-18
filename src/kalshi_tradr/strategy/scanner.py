"""Scan open Kalshi markets for short-dated, lopsided (high-confidence) trades."""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..kalshi.client import KalshiAsyncClient
from ..kalshi.types import LopsidedHit, Market


@dataclass(slots=True)
class ScanParams:
    min_hours: float = 1.0
    max_hours: float = 3.0
    min_prob: float = 0.90
    limit: int = 10


def pick_lopsided(
    markets: list[Market],
    *,
    min_prob: float,
    now_ts: int,
    min_close_ts: int,
    max_close_ts: int,
    limit: int,
) -> list[LopsidedHit]:
    threshold = int(min_prob * 100)
    hits: list[LopsidedHit] = []
    for m in markets:
        if not (min_close_ts <= m.close_ts <= max_close_ts):
            continue
        if m.status and m.status != "open":
            continue
        # Best *ask* is the lowest price a buyer would pay to take a side.
        # We treat "90%+ odds on one side" as: that side's ask is >= threshold.
        for side, ask in (("yes", m.yes_ask), ("no", m.no_ask)):
            if ask is None:
                continue
            if ask >= threshold and ask < 100:
                hits.append(LopsidedHit(market=m, side=side, price_cents=ask))
                break  # only one side can be >= 50% — avoid duplicate
    hits.sort(key=lambda h: (-h.price_cents, h.market.close_ts))
    return hits[:limit]


async def find_lopsided(
    client: KalshiAsyncClient,
    *,
    params: ScanParams,
) -> list[LopsidedHit]:
    now = int(time.time())
    min_close_ts = now + int(params.min_hours * 3600)
    max_close_ts = now + int(params.max_hours * 3600)
    markets = await client.list_open_markets(
        min_close_ts=min_close_ts,
        max_close_ts=max_close_ts,
    )
    return pick_lopsided(
        markets,
        min_prob=params.min_prob,
        now_ts=now,
        min_close_ts=min_close_ts,
        max_close_ts=max_close_ts,
        limit=params.limit,
    )
