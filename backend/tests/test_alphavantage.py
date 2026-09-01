"""Tests for mapping Alpha Vantage payloads onto our models.

Fixtures are real captured responses (public market data, no personal
information). No test makes a network call.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.models import SecurityType
from app.providers.alphavantage import (
    map_daily,
    map_etf_profile,
    map_overview,
)

FIXTURES = Path(__file__).parent / "fixtures" / "alphavantage"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def overview() -> dict:
    return _load("overview_nbis.json")


@pytest.fixture
def etf_profile() -> dict:
    return _load("etf_profile_vt.json")


@pytest.fixture
def daily() -> dict:
    return _load("daily_nvda.json")


# ---- OVERVIEW -> Security ---------------------------------------------------

def test_overview_maps_every_field_the_security_model_needs(overview):
    security = map_overview("NBIS", overview)

    assert security.ticker == "NBIS"
    assert security.name == "Nebius Group N.V."
    assert security.type is SecurityType.stock
    assert security.market_cap == 56_089_174_000
    assert security.beta == 1.434
    assert security.pb == 5.74
    assert security.roe == 0.006


def test_overview_sector_is_title_cased_to_match_the_seed(overview):
    """Alpha Vantage shouts sectors; the seed uses Title Case.

    Mixing the two verbatim would split one sector into two buckets in the
    breakdown.
    """
    assert map_overview("NBIS", overview).sector == "Communication Services"


@pytest.mark.parametrize(
    "av_sector,expected",
    [
        # Alpha Vantage uses a different vocabulary, not just different case.
        ("CONSUMER CYCLICAL", "Consumer Discretionary"),
        ("CONSUMER DEFENSIVE", "Consumer Staples"),
        ("FINANCIAL SERVICES", "Financials"),
        ("HEALTHCARE", "Health Care"),
        ("BASIC MATERIALS", "Materials"),
        # Already matching the seed — pass through, just cased.
        ("TECHNOLOGY", "Technology"),
        ("ENERGY", "Energy"),
        ("COMMUNICATION SERVICES", "Communication Services"),
    ],
)
def test_sectors_are_normalised_onto_one_vocabulary(av_sector, expected):
    """Otherwise a single sector shows up as two rows in the breakdown —
    "Financials" *and* "Financial Services" in the same pie."""
    assert map_overview("X", {"Name": "X", "Sector": av_sector}).sector == expected


def test_seed_and_alphavantage_sectors_do_not_collide():
    """Every sector Alpha Vantage can emit maps into the seed's set."""
    import json
    from pathlib import Path

    seed_path = Path(__file__).parent.parent / "app" / "data" / "etf_seed.json"
    seed_sectors = {
        v["sector"] for v in json.loads(seed_path.read_text())["securities"].values()
        if v.get("sector")
    }
    mapped = {
        map_overview("X", {"Name": "X", "Sector": s}).sector
        for s in ("CONSUMER CYCLICAL", "CONSUMER DEFENSIVE", "FINANCIAL SERVICES", "HEALTHCARE")
    }
    assert mapped <= seed_sectors


def test_overview_country_collapses_to_the_seed_geography_vocabulary(overview):
    # The seed only ever uses "US" or "International".
    assert map_overview("NBIS", overview).geography == "US"


def test_a_non_us_country_is_international():
    security = map_overview("ASML", {"Name": "ASML", "Country": "Netherlands"})
    assert security.geography == "International"


def test_the_literal_string_none_becomes_none_not_zero(overview):
    """NBIS has no P/E, and AV sends the string "None" for it.

    A factor score of 0 means "average"; absent data must stay absent
    (AGENTS.md section 5).
    """
    assert overview["PERatio"] == "None"  # the premise
    assert map_overview("NBIS", overview).pe is None


@pytest.mark.parametrize("blank", ["None", "-", "", "N/A", "none"])
def test_every_blank_spelling_maps_to_none(blank):
    security = map_overview("X", {"Name": "X", "Beta": blank, "MarketCapitalization": blank})
    assert security.beta is None
    assert security.market_cap is None


def test_an_etf_asset_type_is_recognised():
    security = map_overview("VT", {"Name": "Vanguard Total World", "AssetType": "ETF"})
    assert security.type is SecurityType.etf


def test_momentum_is_derived_from_the_moving_averages():
    """50-day above 200-day is positive momentum; 1.0 is flat."""
    security = map_overview(
        "X", {"Name": "X", "50DayMovingAverage": "220", "200DayMovingAverage": "200"}
    )
    assert security.momentum == pytest.approx(1.1)


def test_momentum_is_none_without_both_averages():
    assert map_overview("X", {"Name": "X", "50DayMovingAverage": "220"}).momentum is None


# ---- ETF_PROFILE -> constituents --------------------------------------------

def test_etf_profile_maps_holdings_to_constituents(etf_profile):
    constituents = map_etf_profile(etf_profile)

    assert len(constituents) == 314
    top = constituents[0]
    assert top.ticker == "AAPL"
    assert top.weight == pytest.approx(0.041)


def test_etf_profile_weights_are_fractions_that_do_not_exceed_one(etf_profile):
    total = sum(c.weight for c in map_etf_profile(etf_profile))
    # VT is ~9,000 names; AV returns the top 314, so coverage is partial but
    # must never exceed 100%.
    assert 0.4 < total < 1.0


def test_etf_profile_coverage_beats_the_seed_by_a_wide_margin(etf_profile):
    """The reason this provider exists at all."""
    from app.providers.seed import SeedETFHoldingsProvider

    av = sum(c.weight for c in map_etf_profile(etf_profile))
    seed = sum(c.weight for c in SeedETFHoldingsProvider().get_constituents("VOO"))
    assert av > seed


def test_etf_profile_skips_rows_without_a_symbol():
    payload = {
        "holdings": [
            {"symbol": "AAPL", "description": "APPLE", "weight": "0.05"},
            {"symbol": "n/a", "description": "CASH", "weight": "0.01"},
            {"symbol": "", "description": "OTHER", "weight": "0.01"},
        ]
    }
    assert [c.ticker for c in map_etf_profile(payload)] == ["AAPL"]


def test_an_empty_profile_maps_to_no_constituents():
    assert map_etf_profile({}) == []


# ---- TIME_SERIES_DAILY -> price history -------------------------------------

def test_daily_maps_to_dated_closes_oldest_first(daily):
    series = map_daily(daily)

    assert len(series) == 100
    assert series[0][0] < series[-1][0]
    assert series[-1][0] == date(2026, 9, 1)
    assert series[-1][1] == pytest.approx(217.44)


def test_daily_closes_are_all_positive_floats(daily):
    assert all(isinstance(close, float) and close > 0 for _, close in map_daily(daily))


def test_a_rate_limit_response_maps_to_an_empty_series():
    """AV returns HTTP 200 with an "Information" note when throttled."""
    throttled = {"Information": "Please consider spreading out your free API requests"}
    assert map_daily(throttled) == []
    assert map_etf_profile(throttled) == []
