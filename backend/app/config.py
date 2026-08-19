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
    plaid_products: str = "investments"
    plaid_country_codes: str = "US"
    plaid_redirect_uri: str = ""

    # Upgrade-path market data
    fmp_api_key: str = ""

    # Persistence (Phase 3) — SQLite for the prototype, Postgres later
    database_url: str = "sqlite:///./portfolio.db"

    # App
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def plaid_configured(self) -> bool:
        """True when both Plaid credentials are present."""
        return bool(self.plaid_client_id and self.plaid_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
