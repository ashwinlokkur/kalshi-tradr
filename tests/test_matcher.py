from kalshi_tradr.kalshi.types import Event, Market
from kalshi_tradr.strategy import matcher


def _mk_market(ticker: str, title: str, status: str = "open") -> Market:
    return Market(
        ticker=ticker,
        event_ticker=ticker.split("-")[0],
        title=title,
        subtitle="",
        status=status,
        close_ts=0,
        yes_bid=50,
        yes_ask=51,
        no_bid=49,
        no_ask=50,
        last_price=50,
        volume=0,
    )


def _mk_event(event_ticker: str, title: str, markets: list[Market]) -> Event:
    return Event(
        event_ticker=event_ticker,
        series_ticker="NBA",
        title=title,
        sub_title="",
        markets=markets,
    )


def test_tokenize_strips_stopwords_and_expands_alias():
    toks = matcher.tokenize("put money on GSW vs Lakers today")
    assert "gsw" in toks
    assert "warriors" in toks  # alias expansion
    assert "lakers" in toks
    assert "vs" not in toks
    assert "on" not in toks
    assert "today" not in toks


def test_parse_amount_tail_integer():
    q, amt = matcher.parse_amount_tail("gsw vs lakers 25")
    assert q == "gsw vs lakers"
    assert amt == 25.0


def test_parse_amount_tail_dollar():
    q, amt = matcher.parse_amount_tail("lakers win tonight $42.50")
    assert q == "lakers win tonight"
    assert amt == 42.50


def test_parse_amount_tail_none():
    q, amt = matcher.parse_amount_tail("warriors vs lakers")
    assert q == "warriors vs lakers"
    assert amt is None


def test_rank_candidates_prefers_higher_token_overlap():
    m1 = _mk_market("NBA-LAL-GSW", "Lakers at Warriors — will Warriors win?")
    m2 = _mk_market("NBA-BOS-NYK", "Celtics at Knicks — will Celtics win?")
    ev1 = _mk_event("NBA-LAL-GSW", "Lakers vs Warriors", [m1])
    ev2 = _mk_event("NBA-BOS-NYK", "Celtics vs Knicks", [m2])
    tokens = matcher.tokenize("gsw vs lakers")
    out = matcher.rank_candidates(tokens, [ev1, ev2], top_k=3)
    assert out[0].market.ticker == "NBA-LAL-GSW"
    # Knicks/Celtics event should be filtered out (no token overlap)
    assert all(c.market.ticker != "NBA-BOS-NYK" for c in out)


def test_rank_candidates_skips_closed_markets():
    open_m = _mk_market("NBA-1", "Warriors win", status="open")
    closed_m = _mk_market("NBA-2", "Warriors win again", status="closed")
    ev = _mk_event("NBA-X", "Warriors stuff", [open_m, closed_m])
    tokens = matcher.tokenize("warriors")
    out = matcher.rank_candidates(tokens, [ev])
    assert len(out) == 1
    assert out[0].market.ticker == "NBA-1"
