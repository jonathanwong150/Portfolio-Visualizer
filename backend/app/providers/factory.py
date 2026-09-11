"""Provider factory — selects implementations based on settings.

Prototype defaults return mock/seed providers. Upgrade paths (Plaid, yfinance,
FMP) can be wired here without touching the analytics engine or API layer.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PortfolioDataStatus
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


def get_portfolio_data_status(session: Session) -> PortfolioDataStatus:
    """Describe the holdings source without guessing how stored rows arrived."""
    settings = get_settings()
    if settings.broker_provider == "mock":
        return PortfolioDataStatus.demo

    from app.providers.db_broker import latest_snapshot_at

    if latest_snapshot_at(session) is not None:
        return PortfolioDataStatus.stored
    if settings.broker_provider == "plaid" and settings.plaid_configured:
        return PortfolioDataStatus.empty
    return PortfolioDataStatus.demo


def get_market_data(session: Session | None = None) -> MarketDataProvider:
    settings = get_settings()
    provider = settings.market_provider
    if provider == "seed":
        seed = SeedMarketDataProvider()
        if settings.broker_provider == "mock":
            return seed

        # Precedence, best first: fetched daily closes, then whatever price the
        # broker export carried, then the seed's synthesized series. Fetched
        # data wins because it's refreshed daily and covers every ticker
        # uniformly; the import price is the fallback for things Alpha Vantage
        # can't quote, like a 401(k) collective trust with no ticker.
        from app.providers.snapshot_market import SnapshotMarketDataProvider

        chain: MarketDataProvider = SnapshotMarketDataProvider(seed, session=session)
        if session is not None:
            from app.providers.cached_market import CachedMarketDataProvider

            chain = CachedMarketDataProvider(chain, session=session)
        return chain
    # if provider == "yfinance":
    #     from app.providers.yfinance_provider import YFinanceProvider
    #     return YFinanceProvider()
    raise ValueError(f"Unknown market provider: {provider!r}")


def get_etf_holdings(session: Session | None = None) -> ETFHoldingsProvider:
    provider = get_settings().etf_provider
    if provider == "seed":
        seed = SeedETFHoldingsProvider()
        if session is None:
            return seed
        # Fetched constituents beat the seed's short curated lists; the seed
        # still covers its six ETFs when nothing has been fetched yet.
        from app.providers.cached_market import CachedETFHoldingsProvider

        return CachedETFHoldingsProvider(seed, session=session)
    # if provider == "fmp":
    #     from app.providers.fmp_provider import FMPETFHoldingsProvider
    #     return FMPETFHoldingsProvider()
    raise ValueError(f"Unknown ETF provider: {provider!r}")
