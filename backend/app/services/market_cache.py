"""Persistent cache for Alpha Vantage market data.

The free tier is paced at roughly one request per second, so data is fetched
once and kept. Metadata and ETF constituents change slowly; prices are refreshed
daily and one ``TIME_SERIES_DAILY`` call brings back ~100 days at once.

Raw ``OVERVIEW`` payloads are stored verbatim so a change to the field mapping
costs a re-map rather than a re-fetch.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.tables import EtfConstituentRow, PriceHistoryRow, SecurityMetadataRow
from app.models import ETFConstituent, Security
from app.providers.alphavantage import (
    is_throttled,
    map_daily,
    map_etf_profile,
    map_overview,
)


# ---- metadata ---------------------------------------------------------------

def metadata_row(session: Session, ticker: str) -> SecurityMetadataRow | None:
    return session.get(SecurityMetadataRow, ticker.upper())


def put_metadata(session: Session, ticker: str, payload: dict) -> bool:
    """Store an ``OVERVIEW`` payload. Returns whether it carried usable data.

    An empty payload is stored too, as a negative cache: Alpha Vantage returns
    ``{}`` for a symbol it doesn't list, and without recording that, every
    refresh would spend a call re-asking about it. ``get_security`` reads it back
    as ``None``.
    """
    if is_throttled(payload):
        return False

    ticker = ticker.upper()
    row = metadata_row(session, ticker)
    encoded = json.dumps(payload)
    if row is None:
        session.add(
            SecurityMetadataRow(ticker=ticker, payload=encoded, fetched_at=datetime.utcnow())
        )
    else:
        row.payload = encoded
        row.fetched_at = datetime.utcnow()
    return bool(payload.get("Name"))


def get_security(session: Session, ticker: str) -> Security | None:
    row = metadata_row(session, ticker)
    if row is None:
        return None
    payload = json.loads(row.payload)
    if not payload.get("Name"):
        return None  # cached "Alpha Vantage doesn't list this symbol"
    return map_overview(row.ticker, payload)


def is_unlisted(session: Session, ticker: str) -> bool:
    """True when we've already learned Alpha Vantage doesn't carry this symbol.

    Lets a refresh skip prices and constituents too, instead of spending a call
    per run rediscovering that a 401(k) collective trust has no ticker.
    """
    row = metadata_row(session, ticker)
    return row is not None and not json.loads(row.payload).get("Name")


def metadata_is_stale(session: Session, ticker: str) -> bool:
    row = metadata_row(session, ticker)
    if row is None:
        return True
    ttl = timedelta(days=get_settings().metadata_ttl_days)
    return datetime.utcnow() - row.fetched_at > ttl


# ---- ETF constituents -------------------------------------------------------

def put_constituents(session: Session, etf_ticker: str, payload: dict) -> bool:
    """Replace an ETF's constituents. Returns False if there was no data."""
    if is_throttled(payload):
        return False
    constituents = map_etf_profile(payload)
    if not constituents:
        return False

    etf_ticker = etf_ticker.upper()
    # Replace wholesale: a partial overwrite would leave names that have since
    # dropped out of the fund.
    session.execute(
        delete(EtfConstituentRow).where(EtfConstituentRow.etf_ticker == etf_ticker)
    )
    now = datetime.utcnow()
    for c in constituents:
        session.add(
            EtfConstituentRow(
                etf_ticker=etf_ticker, ticker=c.ticker, weight=c.weight, fetched_at=now
            )
        )
    return True


def get_constituents(session: Session, etf_ticker: str) -> list[ETFConstituent]:
    rows = (
        session.execute(
            select(EtfConstituentRow)
            .where(EtfConstituentRow.etf_ticker == etf_ticker.upper())
            .order_by(EtfConstituentRow.weight.desc())
        )
        .scalars()
        .all()
    )
    return [ETFConstituent(ticker=r.ticker, weight=r.weight) for r in rows]


def constituents_are_stale(session: Session, etf_ticker: str) -> bool:
    row = session.execute(
        select(EtfConstituentRow).where(EtfConstituentRow.etf_ticker == etf_ticker.upper()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return True
    ttl = timedelta(days=get_settings().constituents_ttl_days)
    return datetime.utcnow() - row.fetched_at > ttl


# ---- prices -----------------------------------------------------------------

def put_prices(session: Session, ticker: str, payload: dict) -> bool:
    """Upsert a daily close series. Returns False if there was no data."""
    if is_throttled(payload):
        return False
    series = map_daily(payload)
    if not series:
        return False

    ticker = ticker.upper()
    existing = {
        row.day: row
        for row in session.execute(
            select(PriceHistoryRow).where(PriceHistoryRow.ticker == ticker)
        ).scalars()
    }
    now = datetime.utcnow()
    for day, close in series:
        row = existing.get(day)
        if row is None:
            session.add(
                PriceHistoryRow(ticker=ticker, day=day, close=close, fetched_at=now)
            )
        else:
            row.close = close
            row.fetched_at = now
    return True


def get_prices(session: Session, ticker: str) -> list[tuple[date, float]]:
    rows = (
        session.execute(
            select(PriceHistoryRow.day, PriceHistoryRow.close)
            .where(PriceHistoryRow.ticker == ticker.upper())
            .order_by(PriceHistoryRow.day)
        )
        .all()
    )
    return [(day, close) for day, close in rows]


def prices_are_stale(session: Session, ticker: str) -> bool:
    row = session.execute(
        select(PriceHistoryRow)
        .where(PriceHistoryRow.ticker == ticker.upper())
        .order_by(PriceHistoryRow.fetched_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return True
    ttl = timedelta(hours=get_settings().prices_ttl_hours)
    return datetime.utcnow() - row.fetched_at > ttl


def any_prices_cached(session: Session) -> bool:
    return (
        session.execute(select(PriceHistoryRow.ticker).limit(1)).scalar_one_or_none()
        is not None
    )


def cached_etf_tickers(session: Session) -> set[str]:
    return {
        row
        for row in session.execute(select(EtfConstituentRow.etf_ticker).distinct()).scalars()
    }
