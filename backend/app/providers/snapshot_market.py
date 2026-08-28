"""Market data provider that prefers prices recorded in imported snapshots.

A brokerage export carries authoritative per-share prices, so using them beats
any estimate we could make. Everything the export *doesn't* carry — sector,
fundamentals, price history — is delegated to the wrapped provider.

Each snapshot keeps the prices that were current when it was taken, which is
what makes ``/portfolio/history`` a real net-worth curve rather than one
reconstructed from a synthesized series.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import HoldingRow
from app.models import Security
from app.providers.base import MarketDataProvider


class SnapshotMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        delegate: MarketDataProvider,
        session: Session | None = None,
        session_factory=None,
    ) -> None:
        if session is None and session_factory is None:
            from app.db.session import SessionLocal, init_db

            init_db()
            session_factory = SessionLocal
        self._delegate = delegate
        self._session = session
        self._session_factory = session_factory
        # Analytics call get_price once per position, so the snapshot table is
        # read once per provider instance rather than once per lookup.
        self._by_snapshot: dict[datetime, dict[str, float]] | None = None

    @property
    def prices_are_synthesized(self) -> bool:
        # Any ticker the import didn't price still falls through to the
        # delegate, so the caption has to stay while that's possible.
        return self._delegate.prices_are_synthesized

    def get_security(self, ticker: str) -> Security | None:
        return self._delegate.get_security(ticker)

    def get_price_history(self, ticker: str) -> list[float]:
        return self._delegate.get_price_history(ticker)

    def get_price(self, ticker: str) -> float:
        for at in sorted(self._prices(), reverse=True):
            price = self._prices()[at].get(ticker.upper())
            if price:
                return price
        return self._delegate.get_price(ticker)

    def get_price_on(self, ticker: str, on: date) -> float:
        """The last price observed at or before ``on``, else delegate."""
        candidates = [at for at in self._prices() if at.date() <= on]
        for at in sorted(candidates, reverse=True):
            price = self._prices()[at].get(ticker.upper())
            if price:
                return price
        return self._delegate.get_price_on(ticker, on)

    def _prices(self) -> dict[datetime, dict[str, float]]:
        if self._by_snapshot is None:
            self._by_snapshot = self._load()
        return self._by_snapshot

    @contextmanager
    def _open(self) -> Iterator[Session]:
        """Borrow an injected session, or own a short-lived one."""
        if self._session is not None:
            yield self._session
            return
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def _load(self) -> dict[datetime, dict[str, float]]:
        with self._open() as session:
            rows = session.execute(
                select(HoldingRow.snapshot_at, HoldingRow.ticker, HoldingRow.price).where(
                    HoldingRow.price.is_not(None), HoldingRow.price > 0
                )
            ).all()

        by_snapshot: dict[datetime, dict[str, float]] = {}
        for snapshot_at, ticker, price in rows:
            by_snapshot.setdefault(snapshot_at, {})[ticker.upper()] = price
        return by_snapshot
