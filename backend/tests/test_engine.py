"""Tests for the analytics engine — focus on the look-through resolver."""
from __future__ import annotations

from app.analytics.engine import PortfolioAnalytics
from app.models import AccountType, Holding
from app.providers.base import BrokerAdapter
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
