"""Seed-data implementations of the market-data and ETF-holdings providers.

Loads the curated dataset in ``app/data/etf_seed.json``. Price history is
synthesized deterministically from each security's beta so the risk engine has
data to work with in the prototype (no network calls).
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from app.models import ETFConstituent, Security, SecurityType
from app.providers.base import ETFHoldingsProvider, MarketDataProvider

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "etf_seed.json"


@lru_cache
def _load() -> dict:
    with _DATA_FILE.open() as fh:
        return json.load(fh)


class SeedMarketDataProvider(MarketDataProvider):
    def get_security(self, ticker: str) -> Security | None:
        raw = _load()["securities"].get(ticker)
        if raw is None:
            return None
        return Security(
            ticker=ticker,
            name=raw.get("name", ticker),
            type=SecurityType(raw.get("type", "stock")),
            sector=raw.get("sector"),
            geography=raw.get("geography"),
            market_cap=raw.get("market_cap"),
            beta=raw.get("beta"),
            pe=raw.get("pe"),
            pb=raw.get("pb"),
            roe=raw.get("roe"),
            momentum=raw.get("momentum"),
        )

    def get_price_history(self, ticker: str, days: int = 252) -> list[float]:
        """Synthesize a plausible price series from beta.

        Deterministic pseudo-random walk seeded by the ticker so results are
        reproducible. Higher-beta names get larger daily moves. This is a
        prototype stand-in for real historical prices.
        """
        sec = self.get_security(ticker)
        beta = (sec.beta if sec and sec.beta else 1.0)
        seed = sum(ord(c) for c in ticker)
        price = 100.0
        series: list[float] = [price]
        market_daily_vol = 0.01  # ~1% daily market vol
        drift = 0.0003
        for i in range(1, days):
            # Deterministic "noise" in [-1, 1]
            noise = math.sin(seed * 0.7 + i * 1.3) * math.cos(seed * 0.13 + i * 0.37)
            ret = drift + beta * market_daily_vol * noise
            price = max(1.0, price * (1 + ret))
            series.append(price)
        return series


class SeedETFHoldingsProvider(ETFHoldingsProvider):
    def get_constituents(self, etf_ticker: str) -> list[ETFConstituent]:
        raw = _load()["etf_constituents"].get(etf_ticker, [])
        return [ETFConstituent(ticker=c["ticker"], weight=c["weight"]) for c in raw]

    def is_etf(self, ticker: str) -> bool:
        sec = _load()["securities"].get(ticker)
        return bool(sec and sec.get("type") == "etf")
