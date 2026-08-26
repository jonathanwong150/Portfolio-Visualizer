"""Provider factory — selects implementations based on settings.

Prototype defaults return mock/seed providers. Upgrade paths (Plaid, yfinance,
FMP) can be wired here without touching the analytics engine or API layer.
"""
from __future__ import annotations

from app.config import get_settings
from app.providers.base import BrokerAdapter, ETFHoldingsProvider, MarketDataProvider
from app.providers.mock_broker import MockBroker
from app.providers.seed import SeedETFHoldingsProvider, SeedMarketDataProvider


def get_broker() -> BrokerAdapter:
    provider = get_settings().broker_provider
    if provider == "mock":
        return MockBroker()
    if provider == "plaid":
        from app.providers.plaid_broker import PlaidBroker

        # Mock data keeps the app usable until the first successful Plaid sync.
        return PlaidBroker(fallback=MockBroker())
    raise ValueError(f"Unknown broker provider: {provider!r}")


def get_market_data() -> MarketDataProvider:
    provider = get_settings().market_provider
    if provider == "seed":
        return SeedMarketDataProvider()
    # if provider == "yfinance":
    #     from app.providers.yfinance_provider import YFinanceProvider
    #     return YFinanceProvider()
    raise ValueError(f"Unknown market provider: {provider!r}")


def get_etf_holdings() -> ETFHoldingsProvider:
    provider = get_settings().etf_provider
    if provider == "seed":
        return SeedETFHoldingsProvider()
    # if provider == "fmp":
    #     from app.providers.fmp_provider import FMPETFHoldingsProvider
    #     return FMPETFHoldingsProvider()
    raise ValueError(f"Unknown ETF provider: {provider!r}")
