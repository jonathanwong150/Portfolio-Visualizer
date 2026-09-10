"""Tests for the analytics engine — focus on the look-through resolver."""
from __future__ import annotations

import pytest

from app.analytics.engine import PortfolioAnalytics
from app.models import AccountType, ETFConstituent, Holding, Security, SecurityType
from app.providers.base import BrokerAdapter, ETFHoldingsProvider, MarketDataProvider
from app.providers.seed import SeedETFHoldingsProvider, SeedMarketDataProvider


class _StaticBroker(BrokerAdapter):
    def __init__(self, holdings: list[Holding]) -> None:
        self._holdings = holdings

    def get_holdings(self) -> list[Holding]:
        return self._holdings


def _engine(holdings: list[Holding]) -> PortfolioAnalytics:
    return PortfolioAnalytics(
        broker=_StaticBroker(holdings),
        market=SeedMarketDataProvider(),
        etf=SeedETFHoldingsProvider(),
    )


class _FixedMarket(MarketDataProvider):
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def get_security(self, ticker: str) -> Security | None:
        if ticker not in self._prices:
            return None
        unresolved = ticker.startswith("UNRESOLVED:")
        return Security(
            ticker=ticker,
            name=ticker,
            type=SecurityType.stock,
            sector="Technology",
            geography="US",
            # Synthetic unresolved metadata points opposite the named holding,
            # so its accidental inclusion would visibly change every score.
            pe=50 if unresolved else 20,
            pb=15 if unresolved else 4,
            roe=0 if unresolved else 0.2,
            momentum=0.5 if unresolved else 1.1,
            beta=0 if unresolved else 1.0,
        )

    def get_price_history(self, ticker: str) -> list[float]:
        return [self._prices.get(ticker, 0.0)]


class _FixedETF(ETFHoldingsProvider):
    def __init__(self, constituents: dict[str, list[tuple[str, float]]]) -> None:
        self._constituents = constituents

    def get_constituents(self, etf_ticker: str) -> list[ETFConstituent]:
        return [
            ETFConstituent(ticker=ticker, weight=weight)
            for ticker, weight in self._constituents.get(etf_ticker, [])
        ]

    def is_etf(self, ticker: str) -> bool:
        return ticker in self._constituents


def _fixed_engine(
    holdings: list[Holding], constituents: dict[str, list[tuple[str, float]]]
) -> PortfolioAnalytics:
    tickers = {h.ticker for h in holdings}
    tickers.update(ticker for rows in constituents.values() for ticker, _ in rows)
    # Deliberately provide metadata for the reserved namespace so the factor
    # test proves is_unresolved drives exclusion rather than missing metadata.
    tickers.update(f"UNRESOLVED:{ticker}" for ticker in constituents)
    return PortfolioAnalytics(
        broker=_StaticBroker(holdings),
        market=_FixedMarket({ticker: 100.0 for ticker in tickers}),
        etf=_FixedETF(constituents),
    )


def test_direct_holding_exposure():
    eng = _engine([Holding(ticker="NVDA", shares=10, account_type=AccountType.brokerage)])
    exp = eng.company_exposure()
    assert len(exp) == 1
    assert exp[0].ticker == "NVDA"
    assert exp[0].via_etf_value == 0.0
    assert exp[0].direct_value == eng.total_value


def test_etf_lookthrough_expands_constituents():
    # Pure SPY position should expand into its constituents, not remain as "SPY".
    eng = _engine([Holding(ticker="SPY", shares=10, account_type=AccountType.brokerage)])
    exp = {e.ticker: e for e in eng.company_exposure()}
    assert "AAPL" in exp
    assert exp["AAPL"].via_etf_value > 0
    assert "SPY" in exp["AAPL"].source_etfs


def test_direct_and_etf_exposure_are_netted():
    # NVDA held directly AND inside SPY -> both contributions on one leaf.
    eng = _engine(
        [
            Holding(ticker="NVDA", shares=10, account_type=AccountType.brokerage),
            Holding(ticker="SPY", shares=10, account_type=AccountType.brokerage),
        ]
    )
    exp = {e.ticker: e for e in eng.company_exposure()}
    assert exp["NVDA"].direct_value > 0
    assert exp["NVDA"].via_etf_value > 0
    assert exp["NVDA"].value == exp["NVDA"].direct_value + exp["NVDA"].via_etf_value


def test_exposure_reconciles_to_total_value():
    eng = _engine(
        [
            Holding(ticker="SPY", shares=10, account_type=AccountType.brokerage),
            Holding(ticker="QQQ", shares=5, account_type=AccountType.roth),
            Holding(ticker="AAPL", shares=3, account_type=AccountType.roth),
        ]
    )
    exp = eng.company_exposure()
    assert abs(sum(e.value for e in exp) - eng.total_value) < 1e-6
    assert abs(sum(e.weight for e in exp) - 1.0) < 1e-6


def test_weights_sorted_descending():
    eng = _engine([Holding(ticker="SPY", shares=10, account_type=AccountType.brokerage)])
    exp = eng.company_exposure()
    values = [e.value for e in exp]
    assert values == sorted(values, reverse=True)


def test_risk_metrics_populated():
    eng = _engine(
        [
            Holding(ticker="SPY", shares=10, account_type=AccountType.brokerage),
            Holding(ticker="NVDA", shares=5, account_type=AccountType.brokerage),
        ]
    )
    risk = eng.risk_metrics()
    assert risk.beta is not None and risk.beta > 0
    assert risk.annualized_volatility is not None
    assert risk.max_drawdown is not None and risk.max_drawdown <= 0


# ---- Phase 2: factors & correlation -----------------------------------------

def test_factor_tilts_cover_all_axes():
    eng = _engine([Holding(ticker="QQQ", shares=10, account_type=AccountType.brokerage)])
    tilts = {t.factor: t for t in eng.factor_tilts()}
    for axis in ("style", "size", "momentum", "quality", "beta"):
        assert axis in tilts
        assert -1.0 <= tilts[axis].score <= 1.0
        # high/low weights partition the scored portfolio
        assert abs((tilts[axis].high_weight + tilts[axis].low_weight) - 1.0) < 1e-6


def test_growth_portfolio_tilts_growth():
    # NVDA is high P/E, high P/B -> should tilt toward Growth (positive style).
    eng = _engine([Holding(ticker="NVDA", shares=10, account_type=AccountType.brokerage)])
    style = next(t for t in eng.factor_tilts() if t.factor == "style")
    assert style.score > 0
    assert style.high_label == "Growth"


def test_value_stock_tilts_value():
    # JPM is low P/E, low P/B -> negative style score (value).
    eng = _engine([Holding(ticker="JPM", shares=10, account_type=AccountType.brokerage)])
    style = next(t for t in eng.factor_tilts() if t.factor == "style")
    assert style.score < 0


def test_correlation_matrix_shape_and_diagonal():
    eng = _engine(
        [
            Holding(ticker="SPY", shares=10, account_type=AccountType.brokerage),
            Holding(ticker="QQQ", shares=10, account_type=AccountType.roth),
            Holding(ticker="NVDA", shares=5, account_type=AccountType.roth),
        ]
    )
    cm = eng.correlation_matrix()
    n = len(cm.tickers)
    assert n == 3
    assert len(cm.matrix) == n and all(len(row) == n for row in cm.matrix)
    # diagonal is 1.0 (a series is perfectly correlated with itself)
    for i in range(n):
        assert abs(cm.matrix[i][i] - 1.0) < 1e-6
    # symmetric
    for i in range(n):
        for j in range(n):
            assert abs(cm.matrix[i][j] - cm.matrix[j][i]) < 1e-6


def test_partial_constituent_weights_are_verbatim_with_an_unresolved_remainder():
    eng = _fixed_engine(
        [Holding(ticker="TOY", shares=10, account_type=AccountType.brokerage)],
        {"TOY": [("AAPL", 0.1), ("MSFT", 0.2)]},
    )

    exposure = {e.ticker: e for e in eng.company_exposure()}

    assert exposure["AAPL"].value == pytest.approx(100)
    assert exposure["MSFT"].value == pytest.approx(200)
    unresolved = exposure["UNRESOLVED:TOY"]
    assert unresolved.value == pytest.approx(700)
    assert unresolved.weight == pytest.approx(0.7)
    assert unresolved.name == "Unresolved holdings in TOY"
    assert unresolved.is_unresolved is True
    assert unresolved.source_etfs == ["TOY"]
    assert exposure["AAPL"].is_unresolved is False


def test_direct_and_multiple_etf_exposures_net_without_merging_unresolved_funds():
    eng = _fixed_engine(
        [
            Holding(ticker="AAPL", shares=1, account_type=AccountType.brokerage),
            Holding(ticker="FUND1", shares=10, account_type=AccountType.brokerage),
            Holding(ticker="FUND2", shares=5, account_type=AccountType.roth),
        ],
        {"FUND1": [("AAPL", 0.1)], "FUND2": [("AAPL", 0.5)]},
    )

    exposure = {e.ticker: e for e in eng.company_exposure()}

    assert exposure["AAPL"].value == pytest.approx(450)
    assert exposure["AAPL"].direct_value == pytest.approx(100)
    assert exposure["AAPL"].via_etf_value == pytest.approx(350)
    assert exposure["AAPL"].source_etfs == ["FUND1", "FUND2"]
    assert exposure["UNRESOLVED:FUND1"].value == pytest.approx(900)
    assert exposure["UNRESOLVED:FUND2"].value == pytest.approx(250)


def test_etf_with_no_constituents_is_entirely_unresolved():
    eng = _fixed_engine(
        [Holding(ticker="EMPTY", shares=10, account_type=AccountType.brokerage)],
        {"EMPTY": []},
    )

    assert eng.company_exposure()[0].ticker == "UNRESOLVED:EMPTY"
    assert eng.company_exposure()[0].value == pytest.approx(1000)


def test_fully_covered_etf_has_no_unresolved_row():
    eng = _fixed_engine(
        [Holding(ticker="FULL", shares=10, account_type=AccountType.brokerage)],
        {"FULL": [("AAPL", 0.4), ("MSFT", 0.6)]},
    )

    exposure = eng.company_exposure()

    assert {e.ticker for e in exposure} == {"AAPL", "MSFT"}
    assert sum(e.value for e in exposure) == pytest.approx(eng.total_value)


@pytest.mark.parametrize(
    "constituents",
    [
        [("AAPL", -0.1), ("MSFT", 0.2)],
        [("AAPL", float("nan"))],
        [("AAPL", float("inf"))],
        [("AAPL", 0.6), ("MSFT", 0.400_001)],
    ],
)
def test_invalid_constituent_lists_make_the_entire_fund_unresolved(constituents):
    eng = _fixed_engine(
        [Holding(ticker="BAD", shares=10, account_type=AccountType.brokerage)],
        {"BAD": constituents},
    )

    exposure = eng.company_exposure()

    assert len(exposure) == 1
    assert exposure[0].ticker == "UNRESOLVED:BAD"
    assert exposure[0].value == pytest.approx(eng.total_value)


def test_unresolved_exposure_reconciles_in_sector_unknown_and_is_not_factor_scored():
    eng = _fixed_engine(
        [Holding(ticker="TOY", shares=10, account_type=AccountType.brokerage)],
        {"TOY": [("AAPL", 0.3)]},
    )

    sectors = {slice_.label: slice_ for slice_ in eng.sector_breakdown()}

    assert sectors["Technology"].value == pytest.approx(300)
    assert sectors["Unknown"].value == pytest.approx(700)
    assert sum(slice_.value for slice_ in sectors.values()) == pytest.approx(eng.total_value)
    geographies = {slice_.label: slice_ for slice_ in eng.geography_breakdown()}
    assert geographies["US"].value == pytest.approx(300)
    assert geographies["Unknown"].value == pytest.approx(700)
    tilts = {tilt.factor: tilt for tilt in eng.factor_tilts()}
    assert tilts["style"].score == pytest.approx(-0.15)
    assert tilts["style"].low_weight == pytest.approx(1)
    assert tilts["momentum"].score == pytest.approx(0.2)
    assert tilts["momentum"].high_weight == pytest.approx(1)


def test_lookthrough_totals_still_reconcile_to_net_worth():
    """Whatever the approximation does, no value may be created or lost."""
    eng = _engine(
        [
            Holding(ticker="SPY", shares=30, account_type=AccountType.brokerage),
            Holding(ticker="VTI", shares=40, account_type=AccountType.roth),
            Holding(ticker="NVDA", shares=40, account_type=AccountType.brokerage),
        ]
    )
    total = sum(e.value for e in eng.company_exposure())
    assert total == pytest.approx(eng.total_value)
    assert sum(e.weight for e in eng.company_exposure()) == pytest.approx(1.0)
