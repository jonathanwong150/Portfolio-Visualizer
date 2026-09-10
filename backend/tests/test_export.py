"""Tests for CSV export of holdings and look-through exposure."""
from __future__ import annotations

import csv
import io

from app.models import AccountType, CompanyExposure, Holding, Security, SecurityType
from app.providers.base import MarketDataProvider
from app.services.export import exposure_csv, holdings_csv


class StubMarket(MarketDataProvider):
    """Fixed prices and metadata so expected rows are hand-computable."""

    def __init__(self, securities: dict[str, Security], prices: dict[str, float]) -> None:
        self._securities = securities
        self._prices = prices

    def get_security(self, ticker: str) -> Security | None:
        return self._securities.get(ticker)

    def get_price_history(self, ticker: str) -> list[float]:
        price = self._prices.get(ticker)
        return [price] if price is not None else []


MARKET = StubMarket(
    securities={
        "NVDA": Security(
            ticker="NVDA", name="NVIDIA Corp", type=SecurityType.stock, sector="Technology"
        ),
        # A comma in the name is the classic CSV escaping trap.
        "BRK.B": Security(
            ticker="BRK.B",
            name="Berkshire Hathaway Inc, Class B",
            type=SecurityType.stock,
            sector="Financials",
        ),
    },
    prices={"NVDA": 100.0, "BRK.B": 400.0, "VOO": 500.0},
)

HOLDINGS = [
    Holding(ticker="NVDA", shares=10, account_type=AccountType.brokerage, cost_basis=900),
    Holding(ticker="BRK.B", shares=2.5, account_type=AccountType.roth),
    Holding(ticker="VOO", shares=4, account_type=AccountType._401k, cost_basis=1800),
]


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


# ---- holdings ---------------------------------------------------------------

def test_holdings_csv_header_is_stable():
    header, *_ = _rows(holdings_csv(HOLDINGS, MARKET))
    assert header == [
        "ticker",
        "name",
        "account_type",
        "shares",
        "price",
        "value",
        "cost_basis",
    ]


def test_holdings_csv_values_are_hand_checkable():
    rows = {r[0]: r for r in _rows(holdings_csv(HOLDINGS, MARKET))[1:]}

    # 10 shares at $100 = $1000.
    assert rows["NVDA"][1:] == ["NVIDIA Corp", "brokerage", "10.0", "100.0", "1000.0", "900.0"]
    # 4 shares at $500 = $2000, stored under the AccountType *value*.
    assert rows["VOO"][2] == "401k"
    assert rows["VOO"][5] == "2000.0"


def test_holdings_csv_escapes_a_name_containing_a_comma():
    text = holdings_csv(HOLDINGS, MARKET)
    assert '"Berkshire Hathaway Inc, Class B"' in text

    # Round-trips back to one field, not two.
    row = next(r for r in _rows(text)[1:] if r[0] == "BRK.B")
    assert row[1] == "Berkshire Hathaway Inc, Class B"
    assert len(row) == 7


def test_holdings_csv_falls_back_to_the_ticker_when_metadata_is_missing():
    # VOO has a price but no Security entry in the stub.
    row = next(r for r in _rows(holdings_csv(HOLDINGS, MARKET))[1:] if r[0] == "VOO")
    assert row[1] == "VOO"


def test_holdings_csv_leaves_a_missing_cost_basis_empty_not_zero():
    row = next(r for r in _rows(holdings_csv(HOLDINGS, MARKET))[1:] if r[0] == "BRK.B")
    assert row[6] == ""


def test_holdings_csv_emits_a_header_for_an_empty_portfolio():
    rows = _rows(holdings_csv([], MARKET))
    assert len(rows) == 1
    assert rows[0][0] == "ticker"


# ---- exposure ---------------------------------------------------------------

EXPOSURES = [
    CompanyExposure(
        ticker="NVDA",
        name="NVIDIA Corp",
        value=21_300.0,
        weight=0.15,
        direct_value=5_000.0,
        via_etf_value=16_300.0,
        source_etfs=["VOO", "QQQ"],
    ),
    CompanyExposure(
        ticker="AAPL",
        name="Apple Inc",
        value=14_200.0,
        weight=0.1,
        direct_value=0.0,
        via_etf_value=14_200.0,
        source_etfs=[],
    ),
    CompanyExposure(
        ticker="UNRESOLVED:VOO",
        name="Unresolved holdings in VOO",
        value=7_100.0,
        weight=0.05,
        direct_value=0.0,
        via_etf_value=7_100.0,
        source_etfs=["VOO"],
        is_unresolved=True,
    ),
]


def test_exposure_csv_header_is_stable():
    header, *_ = _rows(exposure_csv(EXPOSURES))
    assert header == [
        "ticker",
        "name",
        "value",
        "weight",
        "direct_value",
        "via_etf_value",
        "source_etfs",
        "is_unresolved",
    ]


def test_exposure_csv_joins_source_etfs_into_one_field():
    rows = _rows(exposure_csv(EXPOSURES))
    nvda = rows[1]
    assert nvda[0] == "NVDA"
    assert nvda[6] == "VOO QQQ"
    # Space-separated, so a spreadsheet doesn't split the field.
    assert len(nvda) == 8


def test_exposure_csv_marks_unresolved_rows_explicitly():
    row = next(r for r in _rows(exposure_csv(EXPOSURES))[1:] if r[0] == "UNRESOLVED:VOO")
    assert row[7] == "True"


def test_exposure_csv_leaves_source_etfs_blank_for_a_direct_only_holding():
    aapl = next(r for r in _rows(exposure_csv(EXPOSURES))[1:] if r[0] == "AAPL")
    assert aapl[6] == ""


def test_exposure_csv_preserves_the_order_it_was_given():
    rows = _rows(exposure_csv(EXPOSURES))[1:]
    assert [r[0] for r in rows] == ["NVDA", "AAPL", "UNRESOLVED:VOO"]


def test_exposure_csv_emits_a_header_for_an_empty_portfolio():
    rows = _rows(exposure_csv([]))
    assert len(rows) == 1
    assert rows[0][0] == "ticker"
