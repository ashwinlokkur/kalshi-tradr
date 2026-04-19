from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Market:
    ticker: str
    event_ticker: str
    title: str
    subtitle: str
    status: str
    close_ts: int
    yes_bid: int | None
    yes_ask: int | None
    no_bid: int | None
    no_ask: int | None
    last_price: int | None
    volume: int | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass(slots=True)
class Event:
    event_ticker: str
    series_ticker: str
    title: str
    sub_title: str
    markets: list[Market] = field(default_factory=list)
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass(slots=True)
class LopsidedHit:
    market: Market
    side: str  # 'yes' | 'no'
    price_cents: int


@dataclass(slots=True)
class OrderResult:
    order_id: str | None
    status: str
    filled_count: int
    remaining_count: int
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass(slots=True)
class Position:
    ticker: str
    position: int
    market_exposure: int  # cents
    realized_pnl: int  # cents
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass(slots=True)
class RestingOrder:
    order_id: str
    ticker: str
    side: str
    action: str
    count: int
    remaining_count: int
    price_cents: int
    status: str
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass(slots=True)
class Balance:
    balance_cents: int
    payout_cents: int

    @property
    def balance_usd(self) -> float:
        return self.balance_cents / 100


@dataclass(slots=True)
class Series:
    ticker: str
    title: str
    category: str
    tags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
