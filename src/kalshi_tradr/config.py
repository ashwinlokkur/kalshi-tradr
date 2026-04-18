from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO_BASE_URL = "https://demo-api.kalshi.co/trade-api/v2"
PROD_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_bot_token: str
    telegram_allowed_chat_ids: str

    kalshi_env: Literal["demo", "prod"] = "demo"
    kalshi_api_key_id: str
    kalshi_private_key_pem_path: Path = Path("./secrets/kalshi.pem")

    database_url: str

    bet_confirm_required: bool = True
    kelly_fraction: float = 0.25
    max_bet_usd: float = 100.0
    edge_buffer: float = 0.02

    scan_min_prob: float = 0.90
    scan_min_hours: float = 1.0
    scan_max_hours: float = 3.0
    scan_limit: int = 10

    log_level: str = "INFO"

    @field_validator("telegram_allowed_chat_ids")
    @classmethod
    def _must_have_at_least_one_chat(cls, v: str) -> str:
        ids = [s.strip() for s in v.split(",") if s.strip()]
        if not ids:
            raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS must list at least one chat id")
        for item in ids:
            int(item)  # raises if not numeric
        return ",".join(ids)

    @property
    def allowed_chat_ids(self) -> set[int]:
        return {int(s) for s in self.telegram_allowed_chat_ids.split(",") if s.strip()}

    @property
    def kalshi_base_url(self) -> str:
        return PROD_BASE_URL if self.kalshi_env == "prod" else DEMO_BASE_URL

    def read_private_key(self) -> str:
        path = self.kalshi_private_key_pem_path
        if not path.exists():
            raise FileNotFoundError(
                f"Kalshi private key not found at {path}. "
                "Generate an API key in the Kalshi dashboard and drop the PEM there."
            )
        return path.read_text()


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
