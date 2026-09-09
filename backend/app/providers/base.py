"""Abstract provider interfaces."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import ClassVar

from app.models import ETFConstituent, Holding, Security


class BrokerAdapter(ABC):
    """Source of a user's holdings across accounts."""

    @abstractmethod
    def get_holdings(self) -> list[Holding]:
        ...

    def get_account_count(self) -> int | None:
        """Known account count, including empty accounts, if identities exist."""
        return None


class MarketDataProvider(ABC):
    """Source of security metadata (sector, market cap, beta, ...)."""

    # True when prices are generated rather than observed, so the UI can label
    # anything derived from them. Real providers leave this False.
    prices_are_synthesized: ClassVar[bool] = False

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

    def get_price_on(self, ticker: str, on: date) -> float:
        """Close on ``on``, clamped to the ends of the available series.

        The default walks back from the newest close by calendar days, which
        treats the series as consecutive calendar days even though it is really
        252 *trading* days — a prototype simplification. A provider with genuine
        dated prices should override this rather than inherit it.
        """
        history = self.get_price_history(ticker)
        if not history:
            return 0.0
        offset = (date.today() - on).days
        if offset <= 0:
            return history[-1]
        if offset >= len(history):
            return history[0]
        return history[-1 - offset]


class ETFHoldingsProvider(ABC):
    """Source of ETF constituents for the look-through engine."""

    @abstractmethod
    def get_constituents(self, etf_ticker: str) -> list[ETFConstituent]:
        ...

    @abstractmethod
    def is_etf(self, ticker: str) -> bool:
        ...
