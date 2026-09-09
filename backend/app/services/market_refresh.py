"""Explicit market-data refresh — the only thing here that makes HTTP calls.

Walks the tickers you actually hold, fetches only what's stale, paces itself for
Alpha Vantage's ~1 request/second free tier, and stops at a call budget so a
large portfolio warms up over several runs rather than being throttled halfway
through and leaving the cache half-populated.

Throttling arrives as HTTP 200 with an ``Information`` note, so the run watches
for that and gives up rather than spending the remaining budget on refusals.
"""
from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SecurityType
from app.providers.alphavantage import (
    REQUEST_INTERVAL_SECONDS,
    fetch_daily,
    fetch_etf_profile,
    fetch_overview,
    has_error,
    is_throttled,
)
from app.providers.db_broker import current_holding_rows
from app.services import market_cache

logger = logging.getLogger(__name__)


class NotConfigured(RuntimeError):
    """Raised when a refresh is requested without an API key."""


class RefreshResult(BaseModel):
    tickers_seen: int = 0
    tickers_refreshed: int = 0
    calls_made: int = 0
    already_fresh: int = 0
    still_stale: int = 0
    stopped_early: bool = False
    throttled: bool = False
    messages: list[str] = Field(default_factory=list)


class EtfCoverage(BaseModel):
    ticker: str
    constituents: int
    # Fraction of the fund's weight the constituent list accounts for. A
    # look-through percentage is only as trustworthy as this number.
    covered_weight: float


class Coverage(BaseModel):
    total_tickers: int = 0
    with_prices: int = 0
    with_metadata: int = 0
    missing: list[str] = Field(default_factory=list)
    etfs: list[EtfCoverage] = Field(default_factory=list)
    configured: bool = True


def _pace() -> None:
    time.sleep(REQUEST_INTERVAL_SECONDS)


def held_tickers(session: Session) -> list[str]:
    """Tickers in each account's latest snapshot, matching the app display."""
    return sorted({row.ticker.upper() for row in current_holding_rows(session)})


def _looks_like_an_etf(session: Session, ticker: str) -> bool:
    if market_cache.get_constituents(session, ticker):
        return True
    security = market_cache.get_security(session, ticker)
    if security is not None:
        return security.type is SecurityType.etf
    from app.providers.factory import get_etf_holdings

    return get_etf_holdings().is_etf(ticker)


def _plan(
    session: Session, tickers: list[str], unlisted: list[str]
) -> list[tuple[str, str, callable, callable]]:
    """Order the work by value, not alphabetically.

    The free tier allows 25 calls a day against a portfolio that wants ~40, so
    a run will usually be cut short. Grouping by job type means the partial
    result is still the most useful one available:

    1. **prices** — net worth is wrong without them
    2. **constituents** — unlocks the look-through, the point of the app
    3. **metadata** — sector and factor detail, the nicest to have last
    """
    prices, constituents, metadata = [], [], []

    for ticker in tickers:
        if market_cache.prices_are_stale(session, ticker):
            prices.append(("prices", ticker, fetch_daily, market_cache.put_prices))

        if _looks_like_an_etf(session, ticker) and market_cache.constituents_are_stale(
            session, ticker
        ):
            constituents.append(
                ("constituents", ticker, fetch_etf_profile, market_cache.put_constituents)
            )

        # An empty OVERVIEW doesn't mean an empty quote: Alpha Vantage carries
        # no overview for many commodity and crypto trusts but prices them fine.
        # So a known-unlisted ticker skips only this job.
        if market_cache.is_unlisted(session, ticker):
            unlisted.append(ticker)
        elif market_cache.metadata_is_stale(session, ticker):
            metadata.append(("metadata", ticker, fetch_overview, market_cache.put_metadata))

    return prices + constituents + metadata


def refresh(session: Session, max_calls: int | None = None) -> RefreshResult:
    """Fetch stale market data for held tickers, within a call budget."""
    settings = get_settings()
    if not settings.alphavantage_configured:
        raise NotConfigured(
            "ALPHAVANTAGE_API_KEY is not set — add it to backend/.env. "
            "Free key: https://www.alphavantage.co/support/#api-key"
        )

    budget = settings.alphavantage_max_calls_per_refresh if max_calls is None else max_calls
    tickers = held_tickers(session)
    result = RefreshResult(tickers_seen=len(tickers))
    refreshed: set[str] = set()

    unlisted: list[str] = []
    jobs = _plan(session, tickers, unlisted)

    for label, ticker, fetch, store in jobs:
        if result.calls_made >= budget:
            result.stopped_early = True
            break
        if result.calls_made:
            _pace()
        result.calls_made += 1

        try:
            payload = fetch(ticker)
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort the run
            logger.warning("Refresh failed for %s %s: %s", ticker, label, exc)
            result.messages.append(f"{ticker} {label}: {exc}")
            continue

        # A note in the body means the daily quota is spent, so stopping beats
        # spending the rest of the budget on refusals. `Error Message` and an
        # empty payload are different — that symbol just isn't carried.
        if is_throttled(payload):
            result.throttled = True
            result.messages.append(
                "Alpha Vantage's free tier allows 25 requests per day and that's now used up. "
                "Everything already fetched is kept — refresh again tomorrow to continue."
            )
            break

        if has_error(payload):
            logger.info("Alpha Vantage has no %s for %s", label, ticker)
            if label == "metadata":
                market_cache.put_metadata(session, ticker, {})
                unlisted.append(ticker)
            continue

        if store(session, ticker, payload):
            refreshed.add(ticker)
        elif label == "metadata":
            unlisted.append(ticker)
        session.commit()

    session.commit()
    result.already_fresh = len(tickers) - len({t for _, t, _, _ in jobs})
    result.still_stale = max(0, len(tickers) - len(refreshed) - result.already_fresh)
    if unlisted:
        result.messages.append(
            "Not carried by Alpha Vantage, so these keep their imported price: "
            + ", ".join(sorted(set(unlisted)))
        )

    result.tickers_refreshed = len(refreshed)
    return result


def coverage(session: Session) -> Coverage:
    """How much of the portfolio has real data behind it."""
    tickers = held_tickers(session)
    report = Coverage(
        total_tickers=len(tickers),
        configured=get_settings().alphavantage_configured,
    )

    for ticker in tickers:
        has_prices = bool(market_cache.get_prices(session, ticker))
        has_metadata = market_cache.get_security(session, ticker) is not None
        report.with_prices += int(has_prices)
        report.with_metadata += int(has_metadata)
        if not has_prices:
            report.missing.append(ticker)

        constituents = market_cache.get_constituents(session, ticker)
        if constituents:
            report.etfs.append(
                EtfCoverage(
                    ticker=ticker,
                    constituents=len(constituents),
                    covered_weight=sum(c.weight for c in constituents),
                )
            )

    return report
