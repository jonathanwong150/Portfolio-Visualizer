"""Tests for the market-data cache and the providers that read it.

The read path must never make a network call — analytics requests stay fast and
work offline. Refreshing is explicit and rate-limited.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.models import SecurityType
from app.providers.cached_market import (
    CachedETFHoldingsProvider,
    CachedMarketDataProvider,
)
from app.providers.seed import SeedETFHoldingsProvider, SeedMarketDataProvider
from app.services import market_cache

FIXTURES = Path(__file__).parent / "fixtures" / "alphavantage"


def _payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ---- cache writes and staleness ---------------------------------------------

def test_metadata_round_trips_through_the_cache(session):
    market_cache.put_metadata(session, "NBIS", _payload("overview_nbis.json"))
    session.commit()

    security = market_cache.get_security(session, "NBIS")
    assert security is not None
    assert security.sector == "Communication Services"
    assert security.beta == 1.434


def test_metadata_is_absent_before_anything_is_cached(session):
    assert market_cache.get_security(session, "NBIS") is None


def test_fresh_metadata_is_not_stale_and_old_metadata_is(session):
    market_cache.put_metadata(session, "NBIS", {"Name": "Nebius"})
    session.commit()
    assert market_cache.metadata_is_stale(session, "NBIS") is False

    row = market_cache.metadata_row(session, "NBIS")
    row.fetched_at = datetime.utcnow() - timedelta(days=365)
    session.commit()
    assert market_cache.metadata_is_stale(session, "NBIS") is True


def test_an_uncached_ticker_counts_as_stale(session):
    assert market_cache.metadata_is_stale(session, "NEVER") is True


def test_constituents_replace_rather_than_accumulate(session):
    market_cache.put_constituents(session, "VT", _payload("etf_profile_vt.json"))
    session.commit()
    first = market_cache.get_constituents(session, "VT")
    assert len(first) == 314

    # A later refresh must not double the rows.
    market_cache.put_constituents(session, "VT", _payload("etf_profile_vt.json"))
    session.commit()
    assert len(market_cache.get_constituents(session, "VT")) == 314


def test_prices_round_trip_and_upsert_by_day(session):
    market_cache.put_prices(session, "NVDA", _payload("daily_nvda.json"))
    session.commit()
    series = market_cache.get_prices(session, "NVDA")
    assert len(series) == 100

    # Re-storing the same window must not duplicate days.
    market_cache.put_prices(session, "NVDA", _payload("daily_nvda.json"))
    session.commit()
    assert len(market_cache.get_prices(session, "NVDA")) == 100


def test_a_throttled_payload_writes_nothing(session):
    throttled = {"Information": "Please consider spreading out your free API requests"}
    assert market_cache.put_prices(session, "NVDA", throttled) is False
    assert market_cache.put_constituents(session, "VT", throttled) is False
    assert market_cache.put_metadata(session, "NVDA", throttled) is False
    session.commit()

    assert market_cache.get_prices(session, "NVDA") == []
    assert market_cache.get_constituents(session, "VT") == []
    assert market_cache.get_security(session, "NVDA") is None


# ---- CachedMarketDataProvider ----------------------------------------------

def test_cached_prices_win_over_the_synthesized_seed(session):
    market_cache.put_prices(session, "NVDA", _payload("daily_nvda.json"))
    session.commit()

    market = CachedMarketDataProvider(SeedMarketDataProvider(), session=session)

    # The seed prices everything at ~$106; the real close is $217.44.
    assert market.get_price("NVDA") == pytest.approx(217.44)
    assert market.get_price_on("NVDA", date(2026, 9, 1)) == pytest.approx(217.44)


def test_cached_metadata_fills_a_gap_the_seed_cannot(session):
    """NBIS is not in the 25-ticker seed at all."""
    assert SeedMarketDataProvider().get_security("NBIS") is None

    market_cache.put_metadata(session, "NBIS", _payload("overview_nbis.json"))
    session.commit()

    market = CachedMarketDataProvider(SeedMarketDataProvider(), session=session)
    security = market.get_security("NBIS")
    assert security is not None
    assert security.sector == "Communication Services"


def test_the_seed_still_answers_for_a_ticker_with_no_cache(session):
    market = CachedMarketDataProvider(SeedMarketDataProvider(), session=session)
    assert market.get_security("NVDA").sector == "Technology"
    assert market.get_price_history("NVDA") == SeedMarketDataProvider().get_price_history("NVDA")


def test_prices_stop_being_flagged_synthesized_once_real_ones_are_cached(session):
    market = CachedMarketDataProvider(SeedMarketDataProvider(), session=session)
    assert market.prices_are_synthesized is True

    market_cache.put_prices(session, "NVDA", _payload("daily_nvda.json"))
    session.commit()

    fresh = CachedMarketDataProvider(SeedMarketDataProvider(), session=session)
    assert fresh.prices_are_synthesized is False


def test_the_read_path_makes_no_network_call(session, monkeypatch):
    """Analytics must stay offline-safe; refresh is the only fetcher."""
    import app.providers.alphavantage as av

    def explode(*args, **kwargs):
        raise AssertionError("the read path must not call Alpha Vantage")

    monkeypatch.setattr(av, "_get", explode)
    market_cache.put_prices(session, "NVDA", _payload("daily_nvda.json"))
    session.commit()

    market = CachedMarketDataProvider(SeedMarketDataProvider(), session=session)
    market.get_price("NVDA")
    market.get_security("UNKNOWN_TICKER")
    market.get_price_history("ALSO_UNKNOWN")


# ---- CachedETFHoldingsProvider ---------------------------------------------

def test_cached_constituents_beat_the_seed(session):
    market_cache.put_constituents(session, "VT", _payload("etf_profile_vt.json"))
    session.commit()

    etf = CachedETFHoldingsProvider(SeedETFHoldingsProvider(), session=session)
    constituents = etf.get_constituents("VT")

    # The seed has no VT at all.
    assert SeedETFHoldingsProvider().get_constituents("VT") == []
    assert len(constituents) == 314
    assert etf.is_etf("VT") is True


def test_an_etf_only_the_seed_knows_still_resolves(session):
    etf = CachedETFHoldingsProvider(SeedETFHoldingsProvider(), session=session)
    assert len(etf.get_constituents("VOO")) > 0
    assert etf.is_etf("VOO") is True


def test_a_cached_etf_is_recognised_as_an_etf_even_without_metadata(session):
    """is_etf drives look-through; having constituents is proof enough."""
    market_cache.put_constituents(session, "GLD", {"holdings": [{"symbol": "X", "weight": "1.0"}]})
    session.commit()

    etf = CachedETFHoldingsProvider(SeedETFHoldingsProvider(), session=session)
    assert etf.is_etf("GLD") is True


def test_an_ordinary_stock_is_not_an_etf(session):
    etf = CachedETFHoldingsProvider(SeedETFHoldingsProvider(), session=session)
    assert etf.is_etf("NVDA") is False


def test_metadata_marking_a_ticker_as_an_etf_is_respected(session):
    market_cache.put_metadata(session, "IBIT", {"Name": "iShares Bitcoin", "AssetType": "ETF"})
    session.commit()

    etf = CachedETFHoldingsProvider(SeedETFHoldingsProvider(), session=session)
    assert etf.is_etf("IBIT") is True
    # But with no constituents it can't be expanded, which the engine handles.
    assert etf.get_constituents("IBIT") == []


def test_cached_security_type_survives_the_round_trip(session):
    market_cache.put_metadata(session, "VT", {"Name": "Vanguard Total World", "AssetType": "ETF"})
    session.commit()
    assert market_cache.get_security(session, "VT").type is SecurityType.etf
