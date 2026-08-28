"""Tests for the snapshot-backed broker that now serves the app by default."""
from __future__ import annotations

from datetime import datetime

from app.db.tables import AccountRow, HoldingRow
from app.models import AccountType, Holding
from app.providers.base import BrokerAdapter
from app.providers.snapshot_broker import SnapshotBroker


class StubFallback(BrokerAdapter):
    def __init__(self) -> None:
        self.calls = 0

    def get_holdings(self) -> list[Holding]:
        self.calls += 1
        return [Holding(ticker="DEMO", shares=1, account_type=AccountType.brokerage)]


def _import_a_snapshot(session_factory) -> None:
    db = session_factory()
    try:
        account = AccountRow(name="Individual", type=AccountType.brokerage.value)
        db.add(account)
        db.flush()
        db.add(
            HoldingRow(
                account_id=account.id, ticker="NVDA", shares=40, snapshot_at=datetime(2026, 8, 1)
            )
        )
        db.commit()
    finally:
        db.close()


def test_falls_back_to_the_demo_portfolio_when_nothing_is_imported(session_factory):
    fallback = StubFallback()
    broker = SnapshotBroker(session_factory=session_factory, fallback=fallback)

    assert [h.ticker for h in broker.get_holdings()] == ["DEMO"]
    assert fallback.calls == 1


def test_real_holdings_win_once_something_is_imported(session_factory):
    _import_a_snapshot(session_factory)
    fallback = StubFallback()
    broker = SnapshotBroker(session_factory=session_factory, fallback=fallback)

    assert [h.ticker for h in broker.get_holdings()] == ["NVDA"]
    # The whole point: the demo data must not be consulted at all.
    assert fallback.calls == 0


def test_empty_and_no_fallback_is_an_empty_portfolio(session_factory):
    broker = SnapshotBroker(session_factory=session_factory, fallback=None)
    assert broker.get_holdings() == []


def test_a_suppressed_fallback_yields_empty_rather_than_demo_data(session_factory):
    """Plaid's case: configured but never synced should not show demo holdings."""
    fallback = StubFallback()
    broker = SnapshotBroker(
        session_factory=session_factory, fallback=fallback, should_fallback=lambda: False
    )

    assert broker.get_holdings() == []
    assert fallback.calls == 0
