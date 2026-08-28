"""Tests for serving prices recorded in an imported snapshot.

A brokerage export already contains authoritative prices. Valuing an imported
position with the synthesized seed series instead turns a $1.00 money-market
fund into ~$106 a share, which is how net worth ended up 4x too high.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app.db.tables import AccountRow, HoldingRow
from app.models import AccountType, Security, SecurityType
from app.providers.base import MarketDataProvider
from app.providers.snapshot_market import SnapshotMarketDataProvider


class StubDelegate(MarketDataProvider):
    """Stands in for the seed provider: a flat, obviously-fake $106.50."""

    prices_are_synthesized = True

    def get_security(self, ticker: str) -> Security | None:
        return Security(ticker=ticker, name=f"{ticker} Inc", type=SecurityType.stock)

    def get_price_history(self, ticker: str) -> list[float]:
        return [100.0, 103.0, 106.5]


def _snapshot(session, at: datetime, rows: list[tuple[str, float, float | None]]) -> None:
    account = session.query(AccountRow).first()
    if account is None:
        account = AccountRow(name="Individual", type=AccountType.brokerage.value)
        session.add(account)
        session.flush()
    for ticker, shares, price in rows:
        session.add(
            HoldingRow(
                account_id=account.id, ticker=ticker, shares=shares, price=price, snapshot_at=at
            )
        )
    session.commit()


def test_an_imported_price_beats_the_synthesized_one(session_factory):
    db = session_factory()
    _snapshot(db, datetime(2026, 8, 28), [("SPAXX", 1502.34, 1.00), ("NVDA", 40, 182.50)])
    db.close()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)

    assert market.get_price("SPAXX") == 1.00
    assert market.get_price("NVDA") == 182.50


def test_a_ticker_with_no_imported_price_falls_back_to_the_delegate(session_factory):
    db = session_factory()
    _snapshot(db, datetime(2026, 8, 28), [("NVDA", 40, None)])
    db.close()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)
    assert market.get_price("NVDA") == 106.5


def test_an_empty_database_delegates_everything(session_factory):
    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)
    assert market.get_price("NVDA") == 106.5
    assert market.get_price_history("NVDA") == [100.0, 103.0, 106.5]


def test_metadata_and_history_still_come_from_the_delegate(session_factory):
    db = session_factory()
    _snapshot(db, datetime(2026, 8, 28), [("NVDA", 40, 182.50)])
    db.close()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)
    assert market.get_security("NVDA").name == "NVDA Inc"
    assert market.get_price_history("NVDA") == [100.0, 103.0, 106.5]


def test_the_newest_snapshot_supplies_the_current_price(session_factory):
    db = session_factory()
    _snapshot(db, datetime(2026, 7, 1), [("NVDA", 40, 150.00)])
    _snapshot(db, datetime(2026, 8, 1), [("NVDA", 40, 182.50)])
    db.close()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)
    assert market.get_price("NVDA") == 182.50


def test_each_snapshot_is_valued_at_its_own_recorded_price(session_factory):
    """This is what makes net-worth history real rather than synthesized."""
    db = session_factory()
    _snapshot(db, datetime(2026, 7, 1), [("NVDA", 40, 150.00)])
    _snapshot(db, datetime(2026, 8, 1), [("NVDA", 40, 182.50)])
    db.close()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)

    assert market.get_price_on("NVDA", date(2026, 7, 1)) == 150.00
    assert market.get_price_on("NVDA", date(2026, 8, 1)) == 182.50


def test_a_date_between_snapshots_uses_the_most_recent_one_at_or_before_it(session_factory):
    db = session_factory()
    _snapshot(db, datetime(2026, 7, 1), [("NVDA", 40, 150.00)])
    _snapshot(db, datetime(2026, 8, 1), [("NVDA", 40, 182.50)])
    db.close()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)
    # Mid-July: the July price is the last one actually observed.
    assert market.get_price_on("NVDA", date(2026, 7, 15)) == 150.00


def test_a_date_before_every_snapshot_falls_back_rather_than_inventing(session_factory):
    db = session_factory()
    _snapshot(db, datetime(2026, 8, 1), [("NVDA", 40, 182.50)])
    db.close()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)
    # Nothing was recorded that early, so the delegate answers.
    early = date(2020, 1, 1)
    assert market.get_price_on("NVDA", early) == StubDelegate().get_price_on("NVDA", early)


def test_prices_stay_flagged_synthesized_while_any_fallback_is_possible(session_factory):
    db = session_factory()
    _snapshot(db, datetime(2026, 8, 28), [("NVDA", 40, 182.50)])
    db.close()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)
    # Some tickers may still be priced by the seed, so the caption must remain.
    assert market.prices_are_synthesized is True


def test_a_zero_or_negative_imported_price_is_ignored(session_factory):
    """A '--' or '$0.00' cell must not value a real position at nothing."""
    db = session_factory()
    _snapshot(db, datetime(2026, 8, 28), [("NVDA", 40, 0.0)])
    db.close()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)
    assert market.get_price("NVDA") == 106.5


def test_snapshot_prices_are_read_once_per_provider_instance(session_factory):
    """Analytics call get_price per position; that must not be a query each time."""
    db = session_factory()
    _snapshot(db, datetime(2026, 8, 28), [("NVDA", 40, 182.50)])
    db.close()

    calls = {"n": 0}

    def counting_factory():
        calls["n"] += 1
        return session_factory()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=counting_factory)
    for _ in range(5):
        market.get_price("NVDA")

    assert calls["n"] == 1


def test_history_lookup_tolerates_a_snapshot_recorded_later_today(session_factory):
    db = session_factory()
    today = datetime.now()
    _snapshot(db, today, [("NVDA", 40, 182.50)])
    db.close()

    market = SnapshotMarketDataProvider(StubDelegate(), session_factory=session_factory)
    assert market.get_price_on("NVDA", (today + timedelta(hours=2)).date()) == 182.50
