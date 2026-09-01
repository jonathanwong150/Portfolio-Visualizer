"""Providers that read the market-data cache, falling back to the seed.

**Neither of these makes a network call.** That mirrors the deliberate choice
documented for Plaid: reads stay fast and work offline, and fetching is the
explicit job of ``services.market_refresh``. Analytics therefore never block on
a rate-limited third party.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import ETFConstituent, Security, SecurityType
from app.providers.base import ETFHoldingsProvider, MarketDataProvider
from app.services import market_cache


class CachedMarketDataProvider(MarketDataProvider):
    def __init__(self, delegate: MarketDataProvider, session: Session) -> None:
        self._delegate = delegate
        self._session = session
        self._price_cache: dict[str, list[tuple[date, float]]] = {}

    @property
    def prices_are_synthesized(self) -> bool:
        """False once any real price is cached.

        Coarse by design: the honest per-ticker answer is what
        ``/market-data/coverage`` reports.
        """
        if market_cache.any_prices_cached(self._session):
            return False
        return self._delegate.prices_are_synthesized

    def get_security(self, ticker: str) -> Security | None:
        cached = market_cache.get_security(self._session, ticker)
        if cached is not None:
            return cached
        return self._delegate.get_security(ticker)

    def _prices(self, ticker: str) -> list[tuple[date, float]]:
        key = ticker.upper()
        if key not in self._price_cache:
            self._price_cache[key] = market_cache.get_prices(self._session, key)
        return self._price_cache[key]

    def get_price_history(self, ticker: str) -> list[float]:
        series = self._prices(ticker)
        if series:
            return [close for _, close in series]
        return self._delegate.get_price_history(ticker)

    def get_price(self, ticker: str) -> float:
        series = self._prices(ticker)
        if series:
            return series[-1][1]
        return self._delegate.get_price(ticker)

    def get_price_on(self, ticker: str, on: date) -> float:
        series = self._prices(ticker)
        if not series:
            return self._delegate.get_price_on(ticker, on)
        # Last close at or before the date; clamp to the oldest we hold.
        candidates = [close for day, close in series if day <= on]
        return candidates[-1] if candidates else series[0][1]


class CachedETFHoldingsProvider(ETFHoldingsProvider):
    def __init__(self, delegate: ETFHoldingsProvider, session: Session) -> None:
        self._delegate = delegate
        self._session = session

    def get_constituents(self, etf_ticker: str) -> list[ETFConstituent]:
        cached = market_cache.get_constituents(self._session, etf_ticker)
        if cached:
            return cached
        return self._delegate.get_constituents(etf_ticker)

    def is_etf(self, ticker: str) -> bool:
        """Constituents are proof; cached metadata is the next best evidence.

        Getting this wrong matters: a fund the engine doesn't recognise is never
        expanded, and shows up as one giant "company".
        """
        if market_cache.get_constituents(self._session, ticker):
            return True
        security = market_cache.get_security(self._session, ticker)
        if security is not None and security.type is SecurityType.etf:
            return True
        return self._delegate.is_etf(ticker)
