"""Provider factory — selects implementations based on settings.

Prototype defaults return mock/seed providers. Upgrade paths (Plaid, yfinance,
FMP) can be wired here without touching the analytics engine or API layer.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import get_settings
from app.providers.base import BrokerAdapter, ETFHoldingsProvider, MarketDataProvider
from app.providers.mock_broker import MockBroker
from app.providers.seed import SeedETFHoldingsProvider, SeedMarketDataProvider

# `session` is the request-scoped session where one exists. Passing it keeps the
# DB-backed providers on the caller's transaction — and, in tests, on the
# in-memory database the `client` fixture injects rather than the real file.


def get_broker(session: Session | None = None) -> BrokerAdapter:
    provider = get_settings().broker_provider
    if provider == "mock":
        return MockBroker()
    if provider == "db":
        from app.providers.snapshot_broker import SnapshotBroker

        # Demo data until the first CSV import or Plaid sync lands.
        return SnapshotBroker(fallback=MockBroker(), session=session)
    if provider == "plaid":
        from app.providers.plaid_broker import PlaidBroker

        # Mock data keeps the app usable until the first successful Plaid sync.
        return PlaidBroker(fallback=MockBroker(), session=session)
    raise ValueError(f"Unknown broker provider: {provider!r}")


def get_market_data(session: Session | None = None) -> MarketDataProvider:
    settings = get_settings()
    provider = settings.market_provider
    if provider == "seed":
        seed = SeedMarketDataProvider()
        if settings.broker_provider == "mock":
            return seed
        # Imported snapshots carry the broker's own prices; prefer them over
        # anything we'd synthesize, and fall back to the seed for the rest.
        from app.providers.snapshot_market import SnapshotMarketDataProvider

        return SnapshotMarketDataProvider(seed, session=session)
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
