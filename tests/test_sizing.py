from kalshi_tradr.strategy import sizing


def test_kelly_zero_edge_at_fair_price():
    # When prob == implied price, edge is 0.
    stake = sizing.kelly_stake_usd(
        bankroll_usd=1000, price_cents=90, prob=0.90, fraction=0.25, cap_usd=100
    )
    assert stake == 0.0


def test_kelly_with_positive_edge():
    # p=0.95, price=0.90 → b = 1/9 ≈ 0.111; edge = 0.95 - 0.05/0.111 ≈ 0.5
    stake = sizing.kelly_stake_usd(
        bankroll_usd=1000, price_cents=90, prob=0.95, fraction=0.25, cap_usd=10_000
    )
    # Exact: 0.25 * 1000 * (0.95 - 0.05/(0.1/0.9)) = 250 * (0.95 - 0.05*9) = 250 * 0.5 = 125
    assert abs(stake - 125.0) < 1e-6


def test_kelly_capped():
    stake = sizing.kelly_stake_usd(
        bankroll_usd=1000, price_cents=90, prob=0.95, fraction=0.25, cap_usd=50
    )
    assert stake == 50.0


def test_size_bet_count_rounds_down():
    sz = sizing.size_bet(
        bankroll_usd=1000, price_cents=90, prob=0.95, fraction=0.25, cap_usd=50
    )
    # $50 budget at 90¢ per contract → 55 contracts exactly (50/0.9 = 55.55)
    assert sz.count == 55
    assert abs(sz.stake_usd - 55 * 0.90) < 1e-6


def test_size_from_explicit_usd():
    sz = sizing.size_from_explicit_usd(amount_usd=25.0, price_cents=95)
    # 25 / 0.95 = 26.3 → 26 contracts, actual stake $24.70
    assert sz.count == 26
    assert abs(sz.stake_usd - 24.70) < 1e-6


def test_size_from_explicit_zero_price():
    sz = sizing.size_from_explicit_usd(amount_usd=25.0, price_cents=0)
    assert sz.count == 0
    assert sz.stake_usd == 0.0


def test_kelly_negative_edge_returns_zero():
    stake = sizing.kelly_stake_usd(
        bankroll_usd=1000, price_cents=90, prob=0.50, fraction=0.25, cap_usd=100
    )
    assert stake == 0.0
