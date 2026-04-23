import time

from kalshi_tradr.kalshi.types import Market
from kalshi_tradr.strategy import scanner


def _mk_market(
    ticker: str,
    *,
    close_ts: int,
    yes_ask: int | None = None,
    no_ask: int | None = None,
    status: str = "open",
) -> Market:
    return Market(
        ticker=ticker,
        event_ticker=ticker,
        title=ticker,
        subtitle="",
        status=status,
        close_ts=close_ts,
        yes_bid=None,
        yes_ask=yes_ask,
        no_bid=None,
        no_ask=no_ask,
        last_price=None,
        volume=0,
    )


def test_pick_lopsided_filters_by_close_window():
    now = int(time.time())
    min_close = now + 3600
    max_close = now + 3 * 3600
    in_window = _mk_market("A", close_ts=now + 2 * 3600, yes_ask=95)
    too_soon = _mk_market("B", close_ts=now + 600, yes_ask=95)
    too_late = _mk_market("C", close_ts=now + 10 * 3600, yes_ask=95)
    hits = scanner.pick_lopsided(
        [in_window, too_soon, too_late],
        min_prob=0.90,
        now_ts=now,
        min_close_ts=min_close,
        max_close_ts=max_close,
        limit=5,
    )
    assert [h.market.ticker for h in hits] == ["A"]


def test_pick_lopsided_picks_higher_side():
    now = int(time.time())
    # no_ask higher than yes_ask → "no" should be picked
    m = _mk_market("D", close_ts=now + 3600, yes_ask=8, no_ask=92)
    hits = scanner.pick_lopsided(
        [m],
        min_prob=0.90,
        now_ts=now,
        min_close_ts=now + 1800,
        max_close_ts=now + 7200,
        limit=5,
    )
    assert len(hits) == 1
    assert hits[0].side == "no"
    assert hits[0].price_cents == 92


def test_pick_lopsided_rejects_below_threshold():
    now = int(time.time())
    m = _mk_market("E", close_ts=now + 3600, yes_ask=85, no_ask=15)
    hits = scanner.pick_lopsided(
        [m],
        min_prob=0.90,
        now_ts=now,
        min_close_ts=now + 1800,
        max_close_ts=now + 7200,
        limit=5,
    )
    assert hits == []


def test_pick_lopsided_sorts_by_price_desc():
    now = int(time.time())
    a = _mk_market("A", close_ts=now + 3600, yes_ask=91)
    b = _mk_market("B", close_ts=now + 3600, yes_ask=99)
    c = _mk_market("C", close_ts=now + 3600, yes_ask=95)
    hits = scanner.pick_lopsided(
        [a, b, c],
        min_prob=0.90,
        now_ts=now,
        min_close_ts=now + 1800,
        max_close_ts=now + 7200,
        limit=5,
    )
    assert [h.market.ticker for h in hits] == ["B", "C", "A"]


def test_pick_lopsided_skips_price_100():
    now = int(time.time())
    m = _mk_market("Z", close_ts=now + 3600, yes_ask=100)
    hits = scanner.pick_lopsided(
        [m],
        min_prob=0.90,
        now_ts=now,
        min_close_ts=now + 1800,
        max_close_ts=now + 7200,
        limit=5,
    )
    assert hits == []
