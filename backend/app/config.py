"""Application configuration loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Prototype defaults use mock/seed data everywhere."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider selection
    broker_provider: str = "mock"      # mock | plaid
    market_provider: str = "seed"      # seed | yfinance
    etf_provider: str = "seed"         # seed | fmp

    # Plaid (Phase 3)
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"

    # Upgrade-path market data
    fmp_api_key: str = ""

    # App
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
