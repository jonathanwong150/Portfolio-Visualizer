"""Broker serving the latest imported snapshot, with an optional demo fallback.

The read path never touches a network, so analytics stay fast and offline-safe;
getting data *in* is the explicit job of CSV import or Plaid sync.

``should_fallback`` exists for Plaid: when Plaid is configured but has never
synced, an empty portfolio is the honest answer, whereas an app with nothing
imported at all is better off showing the demo portfolio than a blank screen.
"""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models import Holding
from app.providers.base import BrokerAdapter
from app.providers.db_broker import DbBroker


class SnapshotBroker(BrokerAdapter):
    def __init__(
        self,
        session_factory=None,
        fallback: BrokerAdapter | None = None,
        should_fallback: Callable[[], bool] | None = None,
        session: Session | None = None,
    ) -> None:
        if session is None and session_factory is None:
            from app.db.session import SessionLocal, init_db

            # Idempotent: keeps the adapter usable outside the app lifespan
            # (scripts, workers) where startup hasn't created the schema.
            init_db()
            session_factory = SessionLocal
        self._session = session
        self._session_factory = session_factory
        self._fallback = fallback
        self._should_fallback = should_fallback or (lambda: True)

    def get_holdings(self) -> list[Holding]:
        # A session passed in belongs to the request; don't close it.
        if self._session is not None:
            holdings = DbBroker(self._session).get_holdings()
        else:
            session = self._session_factory()
            try:
                holdings = DbBroker(session).get_holdings()
            finally:
                session.close()

        if holdings:
            return holdings
        if self._fallback is not None and self._should_fallback():
            return self._fallback.get_holdings()
        return []
