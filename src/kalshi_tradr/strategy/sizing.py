"""Quarter-Kelly bet sizing.

A binary Kalshi contract pays $1 if "yes" resolves. Given a market quote at
`price_cents` cents per contract, buying costs `price_cents / 100` and nets
`b = (1 − price) / price` on a win. The fractional-Kelly stake as a fraction
of bankroll is `fraction * (p - (1-p)/b)`.

We clamp the result into `[0, cap_usd]` and always place at least one contract
when the strategy returned a positive stake (rounded down to integer contracts).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Sizing:
    count: int
    stake_usd: float
    reason: str


def kelly_stake_usd(
    *,
    bankroll_usd: float,
    price_cents: int,
    prob: float,
    fraction: float = 0.25,
    cap_usd: float = 100.0,
) -> float:
    if price_cents <= 0 or price_cents >= 100:
        return 0.0
    price = price_cents / 100.0
    p = max(0.0, min(prob, 0.999))
    b = (1.0 - price) / price
    if b <= 0:
        return 0.0
    edge_fraction = p - (1.0 - p) / b
    if edge_fraction <= 0:
        return 0.0
    stake = fraction * bankroll_usd * edge_fraction
    return max(0.0, min(stake, cap_usd))


def size_bet(
    *,
    bankroll_usd: float,
    price_cents: int,
    prob: float,
    fraction: float = 0.25,
    cap_usd: float = 100.0,
    min_count: int = 1,
) -> Sizing:
    stake = kelly_stake_usd(
        bankroll_usd=bankroll_usd,
        price_cents=price_cents,
        prob=prob,
        fraction=fraction,
        cap_usd=cap_usd,
    )
    if stake <= 0 or price_cents <= 0:
        return Sizing(count=0, stake_usd=0.0, reason="no edge at current price")
    per_contract_usd = price_cents / 100.0
    count = max(min_count, int(stake // per_contract_usd))
    # Recompute the actual stake for the integer number of contracts.
    actual = round(count * per_contract_usd, 2)
    reason = (
        f"quarter Kelly (f={fraction:.2f}, p={prob:.2f}, price={price_cents}¢, "
        f"bankroll=${bankroll_usd:.2f}, cap=${cap_usd:.0f})"
    )
    return Sizing(count=count, stake_usd=actual, reason=reason)


def size_from_explicit_usd(*, amount_usd: float, price_cents: int, min_count: int = 1) -> Sizing:
    if price_cents <= 0 or price_cents >= 100 or amount_usd <= 0:
        return Sizing(count=0, stake_usd=0.0, reason="invalid amount or price")
    per_contract_usd = price_cents / 100.0
    count = max(min_count, int(amount_usd // per_contract_usd))
    actual = round(count * per_contract_usd, 2)
    return Sizing(count=count, stake_usd=actual, reason=f"user-specified ${amount_usd:.2f}")
