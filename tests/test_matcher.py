from kalshi_tradr.kalshi.types import Event, Market, Series
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
    # Warriors/Lakers matchup ranks first
    assert out[0].market.ticker == "NBA-LAL-GSW"
    # Celtics/Knicks may weakly match via the shared NBA series ticker,
    # but its score must be strictly lower.
    other = [c for c in out if c.market.ticker == "NBA-BOS-NYK"]
    if other:
        assert out[0].score > other[0].score


def test_pick_series_routes_sport_keyword():
    nba = Series(ticker="KXNBAGAME", title="NBA games", category="Sports", tags=["basketball", "nba"])
    nfl = Series(ticker="KXNFLGAME", title="NFL games", category="Sports", tags=["football"])
    weather = Series(ticker="KXWEATHER", title="Weather", category="Climate", tags=["weather"])
    # "gsw" expands to ["gsw", "warriors", "golden", "state", "nba", "basketball"]
    tokens = matcher.tokenize("gsw vs lakers")
    picked = matcher.pick_series(tokens, [nba, nfl, weather], top_k=5)
    assert picked[0].ticker == "KXNBAGAME"
    assert all(s.ticker != "KXWEATHER" for s in picked)


def test_pick_series_empty_when_no_match():
    weather = Series(ticker="KXWEATHER", title="Weather", category="Climate", tags=["weather"])
    tokens = matcher.tokenize("gsw vs lakers")
    picked = matcher.pick_series(tokens, [weather])
    assert picked == []


def test_parse_ticker_or_url_bare_event_ticker():
    assert matcher.parse_ticker_or_url("KXNBAGAME-26APR19PHIBOS") == "KXNBAGAME-26APR19PHIBOS"


def test_parse_ticker_or_url_lowercase_ticker():
    assert matcher.parse_ticker_or_url("kxnbagame-26apr19phibos") == "KXNBAGAME-26APR19PHIBOS"


def test_parse_ticker_or_url_full_url():
    url = "https://kalshi.com/markets/kxnbagame/professional-basketball-game/KXNBAGAME-26APR19PHIBOS?utm_source=kalshiapp_eventpage"
    assert matcher.parse_ticker_or_url(url) == "KXNBAGAME-26APR19PHIBOS"


def test_parse_ticker_or_url_url_without_scheme():
    url = "kalshi.com/markets/kxnbagame/x/KXNBAGAME-26APR19PHIBOS"
    assert matcher.parse_ticker_or_url(url) == "KXNBAGAME-26APR19PHIBOS"


def test_parse_ticker_or_url_plain_words_returns_none():
    assert matcher.parse_ticker_or_url("warriors vs lakers") is None


def test_parse_ticker_or_url_non_kalshi_url_returns_none():
    assert matcher.parse_ticker_or_url("https://example.com/KXNBAGAME-26APR19PHIBOS") is None


def test_parse_amount_tail_ignores_digits_inside_url():
    url = "https://kalshi.com/markets/kxnbagame/x/KXNBAGAME-26APR19PHIBOS?utm_source=kalshiapp_eventpage"
    q, amt = matcher.parse_amount_tail(url)
    assert q == url
    assert amt is None


def test_parse_amount_tail_strips_trailing_amount_after_url():
    url = "https://kalshi.com/markets/kxnbagame/x/KXNBAGAME-26APR19PHIBOS 25"
    q, amt = matcher.parse_amount_tail(url)
    assert q.endswith("KXNBAGAME-26APR19PHIBOS")
    assert amt == 25.0


def test_rank_candidates_skips_closed_markets():
    open_m = _mk_market("NBA-1", "Warriors win", status="open")
    closed_m = _mk_market("NBA-2", "Warriors win again", status="closed")
    ev = _mk_event("NBA-X", "Warriors stuff", [open_m, closed_m])
    tokens = matcher.tokenize("warriors")
    out = matcher.rank_candidates(tokens, [ev])
    assert len(out) == 1
    assert out[0].market.ticker == "NBA-1"
