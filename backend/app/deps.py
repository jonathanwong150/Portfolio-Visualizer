"""FastAPI dependency wiring for the analytics engine."""
from __future__ import annotations

from app.analytics.engine import PortfolioAnalytics
from app.providers.factory import get_broker, get_etf_holdings, get_market_data


def get_analytics() -> PortfolioAnalytics:
    return PortfolioAnalytics(
        broker=get_broker(),
        market=get_market_data(),
        etf=get_etf_holdings(),
    )
