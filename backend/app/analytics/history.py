"""Net-worth history over holdings snapshots.

Pure, like the rest of ``analytics/``: callers load the snapshots (see
``providers.db_broker.snapshot_history``) and pass them in. Each snapshot is
valued at the prices in effect *on its own date*, so the curve reflects market
moves as well as holdings changes — valuing every snapshot at today's prices
would flatten the market out and make the series a contributions chart.
"""
from __future__ import annotations

from datetime import datetime

from app.models import Holding, NetWorthPoint
from app.providers.base import MarketDataProvider


def net_worth_series(
    history: list[tuple[datetime, list[Holding]]],
    market: MarketDataProvider,
) -> list[NetWorthPoint]:
    """Value each snapshot at its own date. Order is preserved."""
    return [
        NetWorthPoint(
            snapshot_at=snapshot_at,
            net_worth=sum(
                h.shares * market.get_price_on(h.ticker, snapshot_at.date()) for h in holdings
            ),
            num_holdings=len(holdings),
        )
        for snapshot_at, holdings in history
    ]
