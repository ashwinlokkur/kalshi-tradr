"""Natural-language matcher: "gsw vs lakers" → candidate Kalshi markets."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..kalshi.client import KalshiAsyncClient
from ..kalshi.types import Event, Market

_STOPWORDS = {
    "vs",
    "v",
    "versus",
    "to",
    "on",
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "for",
    "at",
    "over",
    "beat",
    "beats",
    "win",
    "wins",
    "winning",
    "lose",
    "loses",
    "bet",
    "me",
    "place",
    "put",
    "money",
    "today",
    "tonight",
    "tomorrow",
}

# Minimal team / nickname aliases. Extend as needed; kept tiny on purpose.
_ALIASES: dict[str, set[str]] = {
    "gsw": {"warriors", "golden", "state"},
    "lal": {"lakers"},
    "bos": {"celtics"},
    "nyk": {"knicks"},
    "phi": {"sixers", "76ers"},
    "mia": {"heat"},
    "sac": {"kings"},
    "nyy": {"yankees"},
    "bkn": {"nets"},
}


@dataclass(slots=True)
class MatchCandidate:
    market: Market
    event: Event
    score: float


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        if raw in _STOPWORDS:
            continue
        out.append(raw)
        if raw in _ALIASES:
            out.extend(_ALIASES[raw])
    return out


def parse_amount_tail(text: str) -> tuple[str, float | None]:
    """Pull an optional trailing USD amount off the request, e.g. '… lakers 25' or '$25.50'."""
    t = text.strip()
    m = re.search(r"(\$?\d+(?:\.\d+)?)\s*$", t)
    if not m:
        return t, None
    raw = m.group(1).lstrip("$")
    try:
        amount = float(raw)
    except ValueError:
        return t, None
    return t[: m.start()].rstrip(" ,.:;"), amount


def score_event(tokens: list[str], event: Event) -> float:
    if not tokens:
        return 0.0
    haystack = f"{event.title} {event.sub_title} {event.event_ticker}".lower()
    return sum(1.0 for tok in tokens if tok in haystack)


def score_market(tokens: list[str], market: Market) -> float:
    if not tokens:
        return 0.0
    haystack = f"{market.title} {market.subtitle} {market.ticker}".lower()
    return sum(1.0 for tok in tokens if tok in haystack)


def rank_candidates(
    tokens: list[str], events: list[Event], *, top_k: int = 3
) -> list[MatchCandidate]:
    scored: list[MatchCandidate] = []
    for ev in events:
        ev_score = score_event(tokens, ev)
        if ev_score <= 0 and not any(score_market(tokens, m) > 0 for m in ev.markets):
            continue
        for m in ev.markets:
            if m.status and m.status != "open":
                continue
            total = ev_score + score_market(tokens, m)
            if total <= 0:
                continue
            scored.append(MatchCandidate(market=m, event=ev, score=total))
    scored.sort(key=lambda c: (-c.score, c.market.close_ts))
    return scored[:top_k]


async def find_candidates(
    client: KalshiAsyncClient, text: str, *, top_k: int = 3
) -> list[MatchCandidate]:
    tokens = tokenize(text)
    if not tokens:
        return []
    events = await client.list_open_events()
    return rank_candidates(tokens, events, top_k=top_k)
