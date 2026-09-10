"""Tests for writing account-scoped holdings snapshots."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.db.tables import AccountSnapshotRow
from app.models import AccountType
from app.providers.db_broker import DbBroker
from app.services.snapshot import SnapshotAccount, SnapshotHolding, write_snapshot


def test_writes_and_replaces_accounts_independently(session):
    jan = datetime(2024, 1, 1)
    feb = datetime(2024, 2, 1)
    march = datetime(2024, 3, 1)
    taxable = SnapshotAccount(name="Taxable", account_type=AccountType.brokerage)
    roth = SnapshotAccount(name="Roth", account_type=AccountType.roth)

    write_snapshot(
        session,
        [taxable],
        [SnapshotHolding(account_key="Taxable", ticker="NVDA", shares=10)],
        jan,
    )
    write_snapshot(
        session,
        [roth],
        [SnapshotHolding(account_key="Roth", ticker="VTI", shares=5)],
        feb,
    )
    write_snapshot(
        session,
        [taxable],
        [SnapshotHolding(account_key="Taxable", ticker="AAPL", shares=4)],
        march,
    )

    assert {holding.ticker for holding in DbBroker(session).get_holdings()} == {"AAPL", "VTI"}


def test_empty_update_writes_a_marker_and_clears_that_accounts_current_holdings(session):
    jan = datetime(2024, 1, 1)
    feb = datetime(2024, 2, 1)
    account = SnapshotAccount(name="Taxable", account_type=AccountType.brokerage)
    write_snapshot(
        session,
        [account],
        [SnapshotHolding(account_key="Taxable", ticker="NVDA", shares=10)],
        jan,
    )

    write_snapshot(session, [account], [], feb)

    assert DbBroker(session).get_holdings() == []
    markers = session.execute(
        select(AccountSnapshotRow).order_by(AccountSnapshotRow.snapshot_at)
    ).scalars().all()
    assert [marker.snapshot_at for marker in markers] == [jan, feb]


def test_invalid_account_reference_does_not_write_an_empty_snapshot(session):
    account = SnapshotAccount(name="Taxable", account_type=AccountType.brokerage)
    jan = datetime(2024, 1, 1)
    write_snapshot(
        session, [account],
        [SnapshotHolding(account_key="Taxable", ticker="NVDA", shares=10)], jan,
    )

    with pytest.raises(ValueError, match="account"):
        write_snapshot(
            session, [account],
            [SnapshotHolding(account_key="Unknown", ticker="AAPL", shares=5)],
            datetime(2024, 2, 1),
        )

    assert [h.ticker for h in DbBroker(session).get_holdings()] == ["NVDA"]
    markers = session.execute(select(AccountSnapshotRow)).scalars().all()
    assert [marker.snapshot_at for marker in markers] == [jan]
