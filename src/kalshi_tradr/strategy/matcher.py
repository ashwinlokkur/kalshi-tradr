"""Natural-language matcher: "gsw vs lakers" → candidate Kalshi markets."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..kalshi.client import KalshiAsyncClient
from ..kalshi.types import Event, Market, Series

log = logging.getLogger(__name__)

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

# Minimal team / nickname aliases. Each alias also tags the sport/league so
# series-routing has something to grip on even for "gsw vs lakers".
_ALIASES: dict[str, set[str]] = {
    # NBA
    "gsw": {"warriors", "golden", "state", "nba", "basketball"},
    "warriors": {"nba", "basketball"},
    "lal": {"lakers", "nba", "basketball"},
    "lakers": {"nba", "basketball"},
    "bos": {"celtics", "nba", "basketball"},
    "celtics": {"nba", "basketball"},
    "nyk": {"knicks", "nba", "basketball"},
    "knicks": {"nba", "basketball"},
    "phi": {"sixers", "76ers", "nba", "basketball"},
    "sixers": {"nba", "basketball"},
    "mia": {"heat", "nba", "basketball"},
    "heat": {"nba", "basketball"},
    "sac": {"kings", "nba", "basketball"},
    "bkn": {"nets", "nba", "basketball"},
    # MLB
    "nyy": {"yankees", "mlb", "baseball"},
    "yankees": {"mlb", "baseball"},
    # NFL (stub — extend as needed)
    "nfl": {"football"},
    "mlb": {"baseball"},
    "nba": {"basketball"},
    "nhl": {"hockey"},
}


@dataclass(slots=True)
class MatchCandidate:
    market: Market
    event: Event
    score: float


@dataclass(slots=True)
class MatchResult:
    tokens: list[str]
    total_events: int
    matched_events: int
    candidates: list[MatchCandidate]
    sample_titles: list[str] = field(default_factory=list)
    series_used: list[str] = field(default_factory=list)


def score_series(tokens: list[str], series: Series) -> float:
    if not tokens:
        return 0.0
    tags = " ".join(series.tags)
    haystack = f"{series.ticker} {series.title} {series.category} {tags}".lower()
    return sum(1.0 for tok in tokens if tok in haystack)


def pick_series(
    tokens: list[str], all_series: list[Series], *, top_k: int = 5
) -> list[Series]:
    scored = [(score_series(tokens, s), s) for s in all_series]
    scored = [(n, s) for n, s in scored if n > 0]
    scored.sort(key=lambda t: -t[0])
    return [s for _, s in scored[:top_k]]


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
    haystack = (
        f"{event.title} {event.sub_title} {event.event_ticker} {event.series_ticker}"
    ).lower()
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


async def _gather_events(
    client: KalshiAsyncClient, tokens: list[str], *, top_series: int = 5
) -> tuple[list[Event], list[str]]:
    """Series-aware fetch. Returns (events, series_tickers_used).

    Tries /series first: if any series titles/categories/tags overlap the
    query tokens, only pulls events for those series. Otherwise falls back
    to a broad /events fetch.
    """
    try:
        all_series = await client.list_series()
    except Exception as exc:  # pragma: no cover - defensive, fall back to broad fetch
        log.warning("matcher: /series fetch failed (%s); broad-fetching /events", exc)
        return await client.list_open_events(), []

    chosen = pick_series(tokens, all_series, top_k=top_series)
    if not chosen:
        log.info(
            "matcher: no series matched tokens (of %d series); broad /events fetch",
            len(all_series),
        )
        return await client.list_open_events(), []

    log.info(
        "matcher: routed to %d series: %s",
        len(chosen),
        [(s.ticker, s.title) for s in chosen],
    )
    events: list[Event] = []
    for s in chosen:
        ev = await client.list_open_events(series_ticker=s.ticker)
        log.info("matcher: series %s → %d events", s.ticker, len(ev))
        events.extend(ev)
    return events, [s.ticker for s in chosen]


async def find_candidates(
    client: KalshiAsyncClient,
    text: str,
    *,
    top_k: int = 3,
    sample_on_miss: int = 8,
    event_fallback_limit: int = 5,
) -> MatchResult:
    tokens = tokenize(text)
    log.info("matcher: query=%r tokens=%s", text, tokens)
    if not tokens:
        return MatchResult(tokens=tokens, total_events=0, matched_events=0, candidates=[])

    events, series_used = await _gather_events(client, tokens)
    log.info(
        "matcher: fetched %d open events (series_used=%s)", len(events), series_used
    )

    # First pass: rank using whatever markets came inline with the event payload.
    candidates = rank_candidates(tokens, events, top_k=top_k)
    log.info(
        "matcher: first-pass candidates=%d top=%s",
        len(candidates),
        [(c.market.ticker, c.score) for c in candidates[:3]],
    )

    # Fallback: if events match on title but carry no inline markets, fetch their
    # markets explicitly. Kalshi's /events endpoint sometimes returns events
    # without the nested markets array populated.
    if not candidates:
        event_scores = [(score_event(tokens, e), e) for e in events]
        event_scores = [(s, e) for s, e in event_scores if s > 0 and not e.markets]
        event_scores.sort(key=lambda t: -t[0])
        to_probe = [e for _, e in event_scores[:event_fallback_limit]]
        if to_probe:
            log.info(
                "matcher: probing %d matched events with empty market lists: %s",
                len(to_probe),
                [e.event_ticker for e in to_probe],
            )
            hydrated: list[Event] = []
            for ev in to_probe:
                try:
                    ms = await client.list_markets_for_event(ev.event_ticker)
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning(
                        "matcher: fallback fetch failed for %s: %s", ev.event_ticker, exc
                    )
                    continue
                ev.markets = ms
                hydrated.append(ev)
                log.info(
                    "matcher: event %s → %d markets fetched",
                    ev.event_ticker,
                    len(ms),
                )
            candidates = rank_candidates(tokens, hydrated, top_k=top_k)
            log.info(
                "matcher: fallback candidates=%d top=%s",
                len(candidates),
                [(c.market.ticker, c.score) for c in candidates[:3]],
            )

    matched_events = sum(1 for e in events if score_event(tokens, e) > 0)
    sample = []
    if not candidates:
        sample = [e.title for e in events[:sample_on_miss] if e.title]
        log.info(
            "matcher: NO candidates. matched_events=%d sample=%s",
            matched_events,
            sample,
        )

    return MatchResult(
        tokens=tokens,
        total_events=len(events),
        matched_events=matched_events,
        candidates=candidates,
        sample_titles=sample,
        series_used=series_used,
    )
