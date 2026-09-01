"""Application configuration loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Prototype defaults use mock/seed data everywhere."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider selection
    # db serves imported holdings and falls back to mock until you import.
    broker_provider: str = "db"        # db | mock | plaid
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

    # Alpha Vantage (Phase 5) — real prices, fundamentals and ETF constituents.
    alphavantage_api_key: str = ""
    # The free tier asks for ~1 request/second; this caps one refresh run so a
    # large portfolio warms up over several runs instead of being throttled.
    alphavantage_max_calls_per_refresh: int = 40
    # How long cached data is considered fresh.
    metadata_ttl_days: int = 30
    constituents_ttl_days: int = 30
    prices_ttl_hours: int = 12

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

    @property
    def alphavantage_configured(self) -> bool:
        return bool(self.alphavantage_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
