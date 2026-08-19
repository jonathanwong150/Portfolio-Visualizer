"""Tests for PlaidBroker's read path — DB snapshot first, mock fallback second."""
from __future__ import annotations

from datetime import datetime

from app.config import Settings
from app.db.tables import AccountRow, HoldingRow
from app.models import AccountType
from app.providers.mock_broker import MockBroker
from app.providers.plaid_broker import PlaidBroker


def _set_configured(monkeypatch, value: bool) -> None:
    """``get_settings()`` is lru_cached, so patch the property on the class."""
    monkeypatch.setattr(Settings, "plaid_configured", property(lambda self: value))


def test_unconfigured_and_empty_db_falls_back_to_mock(monkeypatch, session_factory):
    _set_configured(monkeypatch, False)
    broker = PlaidBroker(session_factory=session_factory, fallback=MockBroker())
    assert [h.ticker for h in broker.get_holdings()] == [
        h.ticker for h in MockBroker().get_holdings()
    ]


def test_configured_but_never_synced_returns_empty(monkeypatch, session_factory):
    _set_configured(monkeypatch, True)
    broker = PlaidBroker(session_factory=session_factory, fallback=MockBroker())
    assert broker.get_holdings() == []


def test_db_snapshot_wins_over_fallback(monkeypatch, session_factory):
    _set_configured(monkeypatch, False)

    def _boom() -> None:  # pragma: no cover - must never be reached
        raise AssertionError("Plaid must not be called when a snapshot exists.")

    monkeypatch.setattr("app.providers.plaid_broker._plaid_client", _boom)

    session = session_factory()
    account = AccountRow(name="Roth IRA", type=AccountType.roth.value)
    session.add(account)
    session.flush()
    session.add(
        HoldingRow(
            account_id=account.id,
            ticker="VTI",
            shares=40,
            snapshot_at=datetime(2024, 6, 1),
        )
    )
    session.commit()
    session.close()

    holdings = PlaidBroker(session_factory=session_factory, fallback=MockBroker()).get_holdings()
    assert [h.ticker for h in holdings] == ["VTI"]
    assert holdings[0].account_type is AccountType.roth
