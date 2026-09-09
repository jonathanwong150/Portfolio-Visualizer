"""Tests for the explicit market-data refresh.

Every test stubs the HTTP layer — nothing here touches the network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db.tables import AccountRow, AccountSnapshotRow, HoldingRow
from app.models import AccountType
from app.services import market_cache, market_refresh

FIXTURES = Path(__file__).parent / "fixtures" / "alphavantage"
OVERVIEW = json.loads((FIXTURES / "overview_nbis.json").read_text())
PROFILE = json.loads((FIXTURES / "etf_profile_vt.json").read_text())
DAILY = json.loads((FIXTURES / "daily_nvda.json").read_text())
THROTTLED = {"Information": "Please consider spreading out your free API requests"}


class FakeApi:
    """Records calls so pacing and budget behaviour can be asserted."""

    def __init__(self, overview=OVERVIEW, profile=PROFILE, daily=DAILY) -> None:
        self.calls: list[tuple[str, str]] = []
        self._overview, self._profile, self._daily = overview, profile, daily

    def fetch_overview(self, ticker: str) -> dict:
        self.calls.append(("overview", ticker))
        return self._overview

    def fetch_etf_profile(self, ticker: str) -> dict:
        self.calls.append(("profile", ticker))
        return self._profile

    def fetch_daily(self, ticker: str) -> dict:
        self.calls.append(("daily", ticker))
        return self._daily


@pytest.fixture
def api(monkeypatch) -> FakeApi:
    fake = FakeApi()
    monkeypatch.setattr(market_refresh, "fetch_overview", fake.fetch_overview)
    monkeypatch.setattr(market_refresh, "fetch_etf_profile", fake.fetch_etf_profile)
    monkeypatch.setattr(market_refresh, "fetch_daily", fake.fetch_daily)
    # Don't actually sleep between calls in tests.
    monkeypatch.setattr(market_refresh, "_pace", lambda: None)
    return fake


def _holdings(session, tickers: list[str]) -> None:
    account = AccountRow(name="Individual", type=AccountType.brokerage.value)
    session.add(account)
    session.flush()
    from datetime import datetime

    for ticker in tickers:
        session.add(
            HoldingRow(
                account_id=account.id, ticker=ticker, shares=1, snapshot_at=datetime(2026, 9, 1)
            )
        )
    session.commit()


def test_refresh_fetches_metadata_and_prices_for_every_held_ticker(session, api):
    _holdings(session, ["NVDA", "NBIS"])

    result = market_refresh.refresh(session)

    fetched = {ticker for _, ticker in api.calls}
    assert fetched == {"NVDA", "NBIS"}
    assert result.tickers_refreshed == 2
    assert market_cache.get_prices(session, "NVDA")
    assert market_cache.get_security(session, "NBIS") is not None


def test_refresh_is_idempotent_within_the_ttl(session, api):
    _holdings(session, ["NVDA"])
    market_refresh.refresh(session)
    first = len(api.calls)

    second = market_refresh.refresh(session)

    assert len(api.calls) == first, "nothing was stale, so nothing should be fetched"
    assert second.calls_made == 0
    assert second.already_fresh > 0


def test_a_truncated_run_spends_its_budget_on_prices_first(session, api):
    """25 calls/day against ~40 wanted means runs get cut short.

    Prices must come before fundamentals, or a partial run leaves net worth
    wrong while having fetched P/E ratios.
    """
    _holdings(session, ["AAA", "BBB", "CCC"])

    market_refresh.refresh(session, max_calls=3)

    assert [kind for kind, _ in api.calls] == ["daily", "daily", "daily"]


def test_constituents_outrank_metadata(session, api):
    """Look-through is the app's headline; sector detail can wait a day."""
    _holdings(session, ["VT"])
    market_cache.put_metadata(session, "VT", {"Name": "Vanguard Total World", "AssetType": "ETF"})
    market_cache.put_prices(session, "VT", DAILY)  # prices already fresh
    session.commit()
    api.calls.clear()

    market_refresh.refresh(session, max_calls=1)

    assert api.calls == [("profile", "VT")]


def test_refresh_stops_at_the_call_budget(session, api):
    _holdings(session, ["AAA", "BBB", "CCC", "DDD", "EEE"])

    result = market_refresh.refresh(session, max_calls=3)

    assert len(api.calls) == 3
    assert result.calls_made == 3
    assert result.stopped_early is True
    # What it didn't get to must be reported, not silently dropped.
    assert result.still_stale > 0


def test_a_budget_of_zero_fetches_nothing(session, api):
    _holdings(session, ["NVDA"])
    result = market_refresh.refresh(session, max_calls=0)
    assert api.calls == []
    assert result.stopped_early is True


def test_an_etf_also_gets_its_constituents(session, api):
    _holdings(session, ["VT"])
    # Mark it an ETF so the refresh knows to ask for a profile.
    market_cache.put_metadata(session, "VT", {"Name": "Vanguard Total World", "AssetType": "ETF"})
    session.commit()

    market_refresh.refresh(session)

    assert ("profile", "VT") in api.calls
    assert len(market_cache.get_constituents(session, "VT")) == 314


def test_a_plain_stock_is_never_asked_for_a_profile(session, api):
    _holdings(session, ["NVDA"])
    market_cache.put_metadata(session, "NVDA", {"Name": "NVIDIA", "AssetType": "Common Stock"})
    session.commit()

    market_refresh.refresh(session)

    assert not any(kind == "profile" for kind, _ in api.calls)


def test_throttling_is_reported_and_stops_the_run(session, monkeypatch):
    """A 200 carrying a note means the quota is gone; burning the rest is waste."""
    fake = FakeApi(overview=THROTTLED, profile=THROTTLED, daily=THROTTLED)
    monkeypatch.setattr(market_refresh, "fetch_overview", fake.fetch_overview)
    monkeypatch.setattr(market_refresh, "fetch_etf_profile", fake.fetch_etf_profile)
    monkeypatch.setattr(market_refresh, "fetch_daily", fake.fetch_daily)
    monkeypatch.setattr(market_refresh, "_pace", lambda: None)
    _holdings(session, ["AAA", "BBB", "CCC"])

    result = market_refresh.refresh(session)

    assert result.throttled is True
    assert result.tickers_refreshed == 0
    # It gave up rather than spending the whole budget on refusals.
    assert len(fake.calls) < 6


def test_a_symbol_alpha_vantage_does_not_list_never_aborts_the_run(session, monkeypatch):
    """An empty 200 means "unknown symbol", not "rate limited".

    Conflating the two stopped a whole refresh dead at a 401(k) collective
    trust, which has no ticker and so can never be listed.
    """
    calls: list[str] = []

    def overview(ticker: str) -> dict:
        calls.append(ticker)
        return {} if ticker == "CG2060TD" else OVERVIEW

    monkeypatch.setattr(market_refresh, "fetch_overview", overview)
    monkeypatch.setattr(market_refresh, "fetch_etf_profile", lambda t: PROFILE)
    monkeypatch.setattr(market_refresh, "fetch_daily", lambda t: DAILY)
    monkeypatch.setattr(market_refresh, "_pace", lambda: None)
    _holdings(session, ["CG2060TD", "NVDA"])

    result = market_refresh.refresh(session)

    assert result.throttled is False
    # It carried on to NVDA rather than stopping at the unlisted symbol.
    assert "NVDA" in calls
    assert market_cache.get_prices(session, "NVDA")
    assert any("CG2060TD" in m for m in result.messages)


def test_an_unlisted_symbol_is_negatively_cached_so_it_is_asked_about_once(session, monkeypatch):
    calls: list[str] = []

    def overview(ticker: str) -> dict:
        calls.append(ticker)
        return {}

    monkeypatch.setattr(market_refresh, "fetch_overview", overview)
    monkeypatch.setattr(market_refresh, "fetch_daily", lambda t: {})
    monkeypatch.setattr(market_refresh, "fetch_etf_profile", lambda t: {})
    monkeypatch.setattr(market_refresh, "_pace", lambda: None)
    _holdings(session, ["CG2060TD"])

    market_refresh.refresh(session)
    first = len(calls)
    market_refresh.refresh(session)

    assert len(calls) == first, "a known-unlisted symbol must not be re-fetched"
    assert market_cache.get_security(session, "CG2060TD") is None


def test_an_etf_with_no_overview_still_gets_its_prices(session, monkeypatch):
    """GLD and IBIT return an empty OVERVIEW but quote fine.

    Suppressing the whole ticker on an empty overview left them with no prices
    at all, which is the opposite of the point.
    """
    fetched: list[tuple[str, str]] = []

    monkeypatch.setattr(
        market_refresh, "fetch_overview", lambda t: (fetched.append(("overview", t)), {})[1]
    )
    monkeypatch.setattr(
        market_refresh, "fetch_daily", lambda t: (fetched.append(("daily", t)), DAILY)[1]
    )
    monkeypatch.setattr(market_refresh, "fetch_etf_profile", lambda t: PROFILE)
    monkeypatch.setattr(market_refresh, "_pace", lambda: None)
    _holdings(session, ["GLD"])

    market_refresh.refresh(session)
    assert market_cache.get_prices(session, "GLD"), "prices must be fetched anyway"

    # Second run: the overview is known-absent and must not be re-requested,
    # but that must not have blocked the price fetch above.
    fetched.clear()
    market_refresh.refresh(session)
    assert ("overview", "GLD") not in fetched


def test_refresh_with_no_holdings_does_nothing_gracefully(session, api):
    result = market_refresh.refresh(session)
    assert result.tickers_refreshed == 0
    assert api.calls == []


def test_an_unconfigured_key_raises_rather_than_pretending(session, monkeypatch):
    from app.config import Settings

    monkeypatch.setattr(Settings, "alphavantage_configured", property(lambda self: False))
    _holdings(session, ["NVDA"])

    with pytest.raises(market_refresh.NotConfigured):
        market_refresh.refresh(session)


# ---- coverage reporting -----------------------------------------------------

def test_coverage_reports_which_tickers_have_real_data(session, api):
    _holdings(session, ["NVDA", "NBIS"])
    market_refresh.refresh(session)

    coverage = market_refresh.coverage(session)

    assert coverage.total_tickers == 2
    assert coverage.with_prices == 2
    assert coverage.with_metadata == 2
    assert coverage.missing == []


def test_coverage_includes_latest_tickers_from_staggered_accounts(session):
    from datetime import datetime

    taxable = AccountRow(name="Taxable", type=AccountType.brokerage.value)
    roth = AccountRow(name="Roth", type=AccountType.roth.value)
    session.add_all([taxable, roth])
    session.flush()
    jan = datetime(2026, 1, 1)
    feb = datetime(2026, 2, 1)
    session.add_all(
        [
            AccountSnapshotRow(account_id=taxable.id, snapshot_at=jan),
            HoldingRow(account_id=taxable.id, ticker="NVDA", shares=1, snapshot_at=jan),
            AccountSnapshotRow(account_id=roth.id, snapshot_at=feb),
            HoldingRow(account_id=roth.id, ticker="VTI", shares=1, snapshot_at=feb),
        ]
    )
    session.commit()

    assert market_refresh.held_tickers(session) == ["NVDA", "VTI"]
    assert market_refresh.coverage(session).total_tickers == 2


def test_coverage_names_what_is_missing(session):
    _holdings(session, ["NVDA", "MYSTERY"])
    market_cache.put_prices(session, "NVDA", DAILY)
    session.commit()

    coverage = market_refresh.coverage(session)

    assert coverage.with_prices == 1
    assert "MYSTERY" in coverage.missing


def test_coverage_reports_etf_constituent_depth(session):
    _holdings(session, ["VT"])
    market_cache.put_constituents(session, "VT", PROFILE)
    session.commit()

    coverage = market_refresh.coverage(session)
    vt = next(e for e in coverage.etfs if e.ticker == "VT")

    assert vt.constituents == 314
    # ~53% of the fund by weight — the number that tells you how much to trust
    # a look-through percentage.
    assert 0.4 < vt.covered_weight < 1.0
