"""Tests for the Plaid → database sync service."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.tables import AccountRow, HoldingRow, PlaidItemRow, SecurityRow
from app.models import AccountType, SecurityType
from app.services.sync import PlaidNotConfigured, sync_holdings

_PAYLOAD = {
    "accounts": [
        {
            "plaid_account_id": "acct-1",
            "name": "Individual Brokerage",
            "type": AccountType.brokerage,
            "institution": "Test Bank",
        },
        {
            "plaid_account_id": "acct-2",
            "name": "Company 401k",
            "type": AccountType._401k,
            "institution": "Test Bank",
        },
    ],
    "holdings": [
        {
            "plaid_account_id": "acct-1",
            "ticker": "NVDA",
            "name": "NVIDIA Corp",
            "shares": 40.0,
            "cost_basis": 6000.0,
        },
        {
            "plaid_account_id": "acct-1",
            "ticker": "SPY",
            "name": "SPDR S&P 500 ETF",
            "shares": 30.0,
            "cost_basis": 15000.0,
        },
        {
            "plaid_account_id": "acct-2",
            "ticker": "VOO",
            "name": "Vanguard S&P 500 ETF",
            "shares": 35.0,
            "cost_basis": None,
        },
    ],
}


def _configure(monkeypatch, payload: dict | None = None) -> None:
    """Pretend Plaid is configured and stub out the network call.

    ``sync_holdings`` imports ``fetch_investments`` lazily, so the patch has to
    land on the source module.
    """
    monkeypatch.setattr(Settings, "plaid_configured", property(lambda self: True))
    monkeypatch.setattr(
        "app.providers.plaid_broker.fetch_investments",
        lambda access_token: payload or _PAYLOAD,
    )


def _link_item(session) -> None:
    session.add(PlaidItemRow(access_token="access-sandbox-1", item_id="item-1"))
    session.commit()


def test_sync_requires_configuration(monkeypatch, session):
    monkeypatch.setattr(Settings, "plaid_configured", property(lambda self: False))
    with pytest.raises(PlaidNotConfigured):
        sync_holdings(session)


def test_sync_requires_a_linked_item(monkeypatch, session):
    _configure(monkeypatch)
    with pytest.raises(PlaidNotConfigured):
        sync_holdings(session)


def test_sync_persists_accounts_holdings_and_securities(monkeypatch, session):
    _configure(monkeypatch)
    _link_item(session)

    result = sync_holdings(session)

    assert result.accounts == 2
    assert result.holdings == 3
    assert result.snapshot_at is not None

    accounts = {a.plaid_account_id: a for a in session.execute(select(AccountRow)).scalars()}
    assert accounts["acct-2"].type == "401k"
    assert accounts["acct-1"].institution == "Test Bank"

    holdings = session.execute(select(HoldingRow)).scalars().all()
    assert len(holdings) == 3
    assert {h.snapshot_at for h in holdings} == {result.snapshot_at}

    securities = {s.ticker: s for s in session.execute(select(SecurityRow)).scalars()}
    assert securities["SPY"].type == SecurityType.etf.value
    assert securities["NVDA"].type == SecurityType.stock.value
    assert securities["NVDA"].name == "NVIDIA Corp"


def test_resync_appends_a_new_snapshot_without_clobbering_the_old(monkeypatch, session):
    _configure(monkeypatch)
    _link_item(session)

    first = sync_holdings(session)
    second = sync_holdings(session)

    assert second.snapshot_at >= first.snapshot_at
    snapshots = {h.snapshot_at for h in session.execute(select(HoldingRow)).scalars()}
    assert first.snapshot_at in snapshots
    # Accounts are upserted in place rather than duplicated.
    assert len(session.execute(select(AccountRow)).scalars().all()) == 2
