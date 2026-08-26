"""CSV serialization of holdings and look-through exposure.

Pure string-returning functions — the route layer wraps them in a Response.
Uses the stdlib ``csv`` writer rather than f-strings so a security name
containing a comma or quote is escaped rather than silently splitting a column.
"""
from __future__ import annotations

import csv
import io

from app.models import CompanyExposure, Holding
from app.providers.base import MarketDataProvider

HOLDINGS_HEADER = [
    "ticker",
    "name",
    "account_type",
    "shares",
    "price",
    "value",
    "cost_basis",
]

EXPOSURE_HEADER = [
    "ticker",
    "name",
    "value",
    "weight",
    "direct_value",
    "via_etf_value",
    "source_etfs",
]


def _render(header: list[str], rows: list[list[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def holdings_csv(holdings: list[Holding], market: MarketDataProvider) -> str:
    """Raw positions, priced at the latest close."""
    rows: list[list[object]] = []
    for h in holdings:
        security = market.get_security(h.ticker)
        price = market.get_price(h.ticker)
        rows.append(
            [
                h.ticker,
                security.name if security else h.ticker,
                h.account_type.value,
                h.shares,
                price,
                h.shares * price,
                # Blank, not 0 — an unknown cost basis is not a free position.
                "" if h.cost_basis is None else h.cost_basis,
            ]
        )
    return _render(HOLDINGS_HEADER, rows)


def exposure_csv(exposures: list[CompanyExposure]) -> str:
    """True per-company exposure, post look-through, in the order given."""
    rows: list[list[object]] = [
        [
            e.ticker,
            e.name,
            e.value,
            e.weight,
            e.direct_value,
            e.via_etf_value,
            # Space-separated so the field survives a spreadsheet import intact.
            " ".join(e.source_etfs),
        ]
        for e in exposures
    ]
    return _render(EXPOSURE_HEADER, rows)
