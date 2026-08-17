"""Abstract provider interfaces."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import ETFConstituent, Holding, Security


class BrokerAdapter(ABC):
    """Source of a user's holdings across accounts."""

    @abstractmethod
    def get_holdings(self) -> list[Holding]:
        ...


class MarketDataProvider(ABC):
    """Source of security metadata (sector, market cap, beta, ...)."""

    @abstractmethod
    def get_security(self, ticker: str) -> Security | None:
        ...

    @abstractmethod
    def get_price_history(self, ticker: str) -> list[float]:
        """Return a series of closing prices (oldest -> newest)."""
        ...

    def get_price(self, ticker: str) -> float:
        """Latest close. Default derives it from the price history."""
        history = self.get_price_history(ticker)
        return history[-1] if history else 0.0


class ETFHoldingsProvider(ABC):
    """Source of ETF constituents for the look-through engine."""

    @abstractmethod
    def get_constituents(self, etf_ticker: str) -> list[ETFConstituent]:
        ...

    @abstractmethod
    def is_etf(self, ticker: str) -> bool:
        ...
