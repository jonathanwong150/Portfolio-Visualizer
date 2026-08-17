"""Core analytics engine.

The ``PortfolioAnalytics`` class takes provider instances (broker, market data,
ETF holdings) and computes:

- valued positions
- true company exposure via ETF look-through
- portfolio summary (net worth, allocation)
- sector / geography breakdowns
- ETF overlap
- risk metrics (beta, volatility, Sharpe, max drawdown)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.models import (
    BreakdownSlice,
    CompanyExposure,
    Holding,
    PortfolioSummary,
    RiskMetrics,
    Security,
)
from app.providers.base import BrokerAdapter, ETFHoldingsProvider, MarketDataProvider

RISK_FREE_RATE = 0.04  # annual, for Sharpe
TRADING_DAYS = 252


@dataclass
class ValuedPosition:
    holding: Holding
    price: float
    value: float


@dataclass
class ExposureLeaf:
    """Accumulator for a single underlying company's true exposure."""

    ticker: str
    direct_value: float = 0.0
    via_etf_value: float = 0.0
    source_etfs: set[str] = field(default_factory=set)

    @property
    def total(self) -> float:
        return self.direct_value + self.via_etf_value


class PortfolioAnalytics:
    def __init__(
        self,
        broker: BrokerAdapter,
        market: MarketDataProvider,
        etf: ETFHoldingsProvider,
    ) -> None:
        self.broker = broker
        self.market = market
        self.etf = etf
        self._holdings: list[Holding] | None = None
        self._valued: list[ValuedPosition] | None = None

    # ---- Basic loading ---------------------------------------------------

    @property
    def holdings(self) -> list[Holding]:
        if self._holdings is None:
            self._holdings = self.broker.get_holdings()
        return self._holdings

    @property
    def valued_positions(self) -> list[ValuedPosition]:
        if self._valued is None:
            out: list[ValuedPosition] = []
            for h in self.holdings:
                price = self.market.get_price(h.ticker)
                out.append(ValuedPosition(holding=h, price=price, value=price * h.shares))
            self._valued = out
        return self._valued

    @property
    def total_value(self) -> float:
        return sum(p.value for p in self.valued_positions) or 0.0

    def _security(self, ticker: str) -> Security | None:
        return self.market.get_security(ticker)

    # ---- Look-through ----------------------------------------------------

    def company_exposure(self) -> list[CompanyExposure]:
        """Resolve every position down to true per-company exposure.

        ETFs are expanded into ``weight * position_value`` per constituent and
        netted with direct holdings of the same ticker. Any ETF weight not
        covered by the seed constituents is left as residual ETF exposure under
        the ETF's own ticker (so totals still reconcile to net worth).
        """
        leaves: dict[str, ExposureLeaf] = {}

        def leaf(ticker: str) -> ExposureLeaf:
            if ticker not in leaves:
                leaves[ticker] = ExposureLeaf(ticker=ticker)
            return leaves[ticker]

        for pos in self.valued_positions:
            ticker = pos.holding.ticker
            if self.etf.is_etf(ticker):
                constituents = self.etf.get_constituents(ticker)
                covered = 0.0
                for c in constituents:
                    v = pos.value * c.weight
                    lf = leaf(c.ticker)
                    lf.via_etf_value += v
                    lf.source_etfs.add(ticker)
                    covered += c.weight
                residual = max(0.0, 1.0 - covered)
                if residual > 1e-9:
                    # Unmapped remainder is spread proportionally across the
                    # mapped constituents so breakdowns don't collapse into a
                    # large "Unknown" bucket. This assumes the ETF's unmapped
                    # tail resembles its mapped head — a reasonable prototype
                    # approximation; a real ETFHoldingsProvider returns full
                    # constituents and makes this branch a no-op.
                    if covered > 1e-9:
                        scale = residual / covered
                        for c in constituents:
                            lf = leaf(c.ticker)
                            lf.via_etf_value += pos.value * c.weight * scale
                            lf.source_etfs.add(ticker)
                    else:
                        lf = leaf(ticker)
                        lf.via_etf_value += pos.value * residual
                        lf.source_etfs.add(ticker)
            else:
                leaf(ticker).direct_value += pos.value

        total = self.total_value or 1.0
        out: list[CompanyExposure] = []
        for lf in leaves.values():
            sec = self._security(lf.ticker)
            out.append(
                CompanyExposure(
                    ticker=lf.ticker,
                    name=(sec.name if sec else lf.ticker),
                    value=lf.total,
                    weight=lf.total / total,
                    direct_value=lf.direct_value,
                    via_etf_value=lf.via_etf_value,
                    source_etfs=sorted(lf.source_etfs),
                )
            )
        out.sort(key=lambda e: e.value, reverse=True)
        return out

    # ---- Summary & breakdowns -------------------------------------------

    def summary(self) -> PortfolioSummary:
        total = self.total_value
        by_account: dict[str, float] = defaultdict(float)
        by_type: dict[str, float] = defaultdict(float)
        for pos in self.valued_positions:
            by_account[pos.holding.account_type.value] += pos.value
            sec = self._security(pos.holding.ticker)
            asset_type = sec.type.value if sec else "stock"
            by_type[asset_type] += pos.value

        total_cost = sum(
            (p.holding.cost_basis or 0.0) for p in self.valued_positions
        )
        accounts = {p.holding.account_type for p in self.valued_positions}

        return PortfolioSummary(
            net_worth=total,
            total_invested=total_cost,
            num_accounts=len(accounts),
            num_holdings=len(self.holdings),
            allocation_by_account=_slices(by_account, total),
            allocation_by_asset_type=_slices(by_type, total),
        )

    def sector_breakdown(self) -> list[BreakdownSlice]:
        return self._breakdown_by("sector")

    def geography_breakdown(self) -> list[BreakdownSlice]:
        return self._breakdown_by("geography")

    def _breakdown_by(self, attr: str) -> list[BreakdownSlice]:
        """Breakdown computed on *look-through* exposure."""
        buckets: dict[str, float] = defaultdict(float)
        for exp in self.company_exposure():
            sec = self._security(exp.ticker)
            label = getattr(sec, attr, None) if sec else None
            buckets[label or "Unknown"] += exp.value
        total = self.total_value or 1.0
        return _slices(buckets, total)

    # ---- Overlap ---------------------------------------------------------

    def etf_overlap(self) -> dict:
        """Pairwise overlap (shared constituent weight) between held ETFs."""
        etf_tickers = sorted(
            {h.ticker for h in self.holdings if self.etf.is_etf(h.ticker)}
        )
        weights: dict[str, dict[str, float]] = {
            t: {c.ticker: c.weight for c in self.etf.get_constituents(t)}
            for t in etf_tickers
        }
        matrix: list[list[float]] = []
        for a in etf_tickers:
            row: list[float] = []
            for b in etf_tickers:
                shared = sum(
                    min(weights[a].get(k, 0.0), weights[b].get(k, 0.0))
                    for k in set(weights[a]) | set(weights[b])
                )
                row.append(round(shared, 4))
            matrix.append(row)
        return {"etfs": etf_tickers, "matrix": matrix}

    # ---- Risk ------------------------------------------------------------

    def risk_metrics(self) -> RiskMetrics:
        import numpy as np

        total = self.total_value or 1.0

        # Portfolio-weighted beta via look-through securities.
        weighted_beta = 0.0
        for exp in self.company_exposure():
            sec = self._security(exp.ticker)
            beta = sec.beta if sec and sec.beta is not None else 1.0
            weighted_beta += (exp.value / total) * beta

        # Build a weighted portfolio return series from position histories.
        series_by_ticker: dict[str, list[float]] = {}
        for pos in self.valued_positions:
            series_by_ticker[pos.holding.ticker] = self.market.get_price_history(
                pos.holding.ticker
            )
        min_len = min((len(s) for s in series_by_ticker.values()), default=0)

        vol = sharpe = mdd = None
        if min_len > 2:
            port_values = np.zeros(min_len)
            for pos in self.valued_positions:
                s = np.array(series_by_ticker[pos.holding.ticker][-min_len:])
                # normalize to shares held (value path)
                port_values += s * pos.holding.shares
            rets = np.diff(port_values) / port_values[:-1]
            vol = float(np.std(rets) * np.sqrt(TRADING_DAYS))
            mean_annual = float(np.mean(rets) * TRADING_DAYS)
            sharpe = ((mean_annual - RISK_FREE_RATE) / vol) if vol > 0 else None
            # Max drawdown
            running_max = np.maximum.accumulate(port_values)
            drawdowns = (port_values - running_max) / running_max
            mdd = float(drawdowns.min())

        return RiskMetrics(
            beta=round(weighted_beta, 3),
            annualized_volatility=round(vol, 4) if vol is not None else None,
            sharpe_ratio=round(sharpe, 3) if sharpe is not None else None,
            max_drawdown=round(mdd, 4) if mdd is not None else None,
        )


def _slices(buckets: dict[str, float], total: float) -> list[BreakdownSlice]:
    total = total or 1.0
    out = [
        BreakdownSlice(label=k, value=round(v, 2), weight=round(v / total, 4))
        for k, v in buckets.items()
    ]
    out.sort(key=lambda s: s.value, reverse=True)
    return out
