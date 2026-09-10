"""Tests for the snapshot-reading database broker."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.db.tables import AccountRow, AccountSnapshotRow, HoldingRow
from app.models import AccountType
from app.providers.db_broker import (
    DbBroker,
    current_holding_rows,
    latest_account_snapshot_times,
)


def _account(session, type_: AccountType, name: str = "Test Account") -> AccountRow:
    row = AccountRow(name=name, type=type_.value, institution="Test Bank")
    session.add(row)
    session.flush()
    return row


def test_empty_database_returns_no_holdings(session):
    assert DbBroker(session).get_holdings() == []


def test_only_newest_snapshot_is_returned(session):
    account = _account(session, AccountType.brokerage)
    old = datetime(2024, 1, 1, 12, 0, 0)
    new = old + timedelta(days=1)
    session.add_all(
        [
            HoldingRow(account_id=account.id, ticker="NVDA", shares=10, snapshot_at=old),
            HoldingRow(account_id=account.id, ticker="AAPL", shares=5, snapshot_at=old),
            HoldingRow(account_id=account.id, ticker="SPY", shares=3, snapshot_at=new),
        ]
    )
    session.commit()

    holdings = DbBroker(session).get_holdings()
    assert [h.ticker for h in holdings] == ["SPY"]
    assert holdings[0].shares == 3


def test_account_type_round_trips_through_the_value_string(session):
    retirement = _account(session, AccountType._401k, name="Fidelity 401k")
    roth = _account(session, AccountType.roth, name="Roth IRA")
    assert retirement.type == "401k"  # stored as the value, not the member name

    now = datetime(2024, 6, 1, 9, 30, 0)
    session.add_all(
        [
            HoldingRow(account_id=retirement.id, ticker="VOO", shares=35, snapshot_at=now),
            HoldingRow(
                account_id=roth.id, ticker="VTI", shares=40, cost_basis=9000, snapshot_at=now
            ),
        ]
    )
    session.commit()

    by_ticker = {h.ticker: h for h in DbBroker(session).get_holdings()}
    assert by_ticker["VOO"].account_type is AccountType._401k
    assert by_ticker["VTI"].account_type is AccountType.roth
    assert by_ticker["VTI"].cost_basis == 9000
    assert by_ticker["VOO"].cost_basis is None


def test_current_holdings_use_each_accounts_latest_snapshot(session):
    taxable = _account(session, AccountType.brokerage, name="Taxable")
    roth = _account(session, AccountType.roth, name="Roth")
    jan = datetime(2024, 1, 1)
    feb = datetime(2024, 2, 1)
    march = datetime(2024, 3, 1)
    session.add_all(
        [
            AccountSnapshotRow(account_id=taxable.id, snapshot_at=jan),
            HoldingRow(account_id=taxable.id, ticker="NVDA", shares=10, snapshot_at=jan),
            AccountSnapshotRow(account_id=roth.id, snapshot_at=feb),
            HoldingRow(account_id=roth.id, ticker="VTI", shares=5, snapshot_at=feb),
            AccountSnapshotRow(account_id=taxable.id, snapshot_at=march),
            HoldingRow(account_id=taxable.id, ticker="AAPL", shares=4, snapshot_at=march),
        ]
    )
    session.commit()

    assert latest_account_snapshot_times(session) == {taxable.id: march, roth.id: feb}
    assert {row.ticker for row in current_holding_rows(session)} == {"AAPL", "VTI"}
    assert {holding.ticker for holding in DbBroker(session).get_holdings()} == {"AAPL", "VTI"}


def test_legacy_unmarked_holdings_still_use_each_accounts_latest_snapshot(session):
    taxable = _account(session, AccountType.brokerage, name="Taxable")
    roth = _account(session, AccountType.roth, name="Roth")
    jan = datetime(2024, 1, 1)
    feb = datetime(2024, 2, 1)
    session.add_all(
        [
            HoldingRow(account_id=taxable.id, ticker="NVDA", shares=10, snapshot_at=jan),
            HoldingRow(account_id=roth.id, ticker="VTI", shares=5, snapshot_at=feb),
        ]
    )
    session.commit()

    assert {holding.ticker for holding in DbBroker(session).get_holdings()} == {"NVDA", "VTI"}
