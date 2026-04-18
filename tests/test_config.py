import pytest

from kalshi_tradr.config import DEMO_BASE_URL, PROD_BASE_URL, Settings


def _kwargs(**overrides):
    base = {
        "telegram_bot_token": "t",
        "telegram_allowed_chat_ids": "1,2",
        "kalshi_api_key_id": "k",
        "database_url": "postgresql://u:p@localhost/db",
    }
    base.update(overrides)
    return base


def test_defaults_demo_env(monkeypatch):
    monkeypatch.setattr(Settings, "model_config", Settings.model_config.copy())
    s = Settings(**_kwargs())
    assert s.kalshi_env == "demo"
    assert s.kalshi_base_url == DEMO_BASE_URL
    assert s.bet_confirm_required is True
    assert s.kelly_fraction == 0.25
    assert s.max_bet_usd == 100.0


def test_prod_env_switch():
    s = Settings(**_kwargs(kalshi_env="prod"))
    assert s.kalshi_base_url == PROD_BASE_URL


def test_allowed_chat_ids_parses_csv():
    s = Settings(**_kwargs(telegram_allowed_chat_ids=" 123 , 456 "))
    assert s.allowed_chat_ids == {123, 456}


def test_allowed_chat_ids_must_be_numeric():
    with pytest.raises(Exception):
        Settings(**_kwargs(telegram_allowed_chat_ids="abc,def"))


def test_allowed_chat_ids_must_not_be_empty():
    with pytest.raises(Exception):
        Settings(**_kwargs(telegram_allowed_chat_ids=""))
