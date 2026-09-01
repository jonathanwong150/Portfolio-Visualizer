"""Alpha Vantage client and payload mapping.

Split deliberately: the ``map_*`` functions are pure and carry all the logic
worth testing, while ``fetch_*`` does nothing but HTTP. No DB access here — the
cache lives in ``services.market_cache``.

Two Alpha Vantage behaviours drive the shape of this module:

* **Throttling returns HTTP 200** with an ``Information`` note instead of an
  error status, so a successful-looking response can contain no data. Every
  mapper treats a missing payload section as empty rather than raising.
* **Missing numbers arrive as the string ``"None"``**, which would become 0.0
  under a naive ``float()`` and read as "average" in the factor engine.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from app.config import get_settings
from app.models import ETFConstituent, Security, SecurityType

logger = logging.getLogger(__name__)

_BASE = "https://www.alphavantage.co/query"

# Alpha Vantage's free tier asks for no more than one request per second.
REQUEST_INTERVAL_SECONDS = 1.5

_BLANKS = frozenset({"", "-", "--", "none", "n/a", "na", "nan"})


class AlphaVantageNotConfigured(RuntimeError):
    """Raised when a fetch is attempted without an API key."""


def _num(raw) -> float | None:
    """Alpha Vantage numerics, where absent is the string ``"None"``."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text.lower() in _BLANKS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# Alpha Vantage and the seed dataset use different sector vocabularies, not just
# different capitalisation. Left unmapped, one sector lands in two buckets —
# "Financials" and "Financial Services" both appearing in the same breakdown.
_SECTOR_ALIASES = {
    "consumer cyclical": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "financial services": "Financials",
    "financial": "Financials",
    "healthcare": "Health Care",
    "basic materials": "Materials",
    "trade & services": "Industrials",
    "manufacturing": "Industrials",
    "life sciences": "Health Care",
}


def _sector(sector: str | None) -> str | None:
    """Normalise a sector onto the seed's vocabulary."""
    if not sector or sector.strip().lower() in _BLANKS:
        return None
    key = " ".join(sector.split()).lower()
    if key in _SECTOR_ALIASES:
        return _SECTOR_ALIASES[key]
    return " ".join(word.capitalize() for word in sector.split())


def _geography(country: str | None) -> str | None:
    """Collapse a country to the seed's two-value vocabulary."""
    if not country or country.strip().lower() in _BLANKS:
        return None
    return "US" if country.strip().upper() in {"USA", "US", "UNITED STATES"} else "International"


def map_overview(ticker: str, payload: dict) -> Security:
    """An ``OVERVIEW`` response as a :class:`Security`."""
    asset_type = (payload.get("AssetType") or "").strip().lower()
    security_type = SecurityType.etf if asset_type == "etf" else SecurityType.stock

    fifty = _num(payload.get("50DayMovingAverage"))
    two_hundred = _num(payload.get("200DayMovingAverage"))
    # Trailing relative strength, matching the seed's convention where 1.0 is
    # flat. Needs both averages; one alone says nothing.
    momentum = fifty / two_hundred if fifty and two_hundred else None

    return Security(
        ticker=ticker.upper(),
        name=(payload.get("Name") or ticker).strip(),
        type=security_type,
        sector=_sector(payload.get("Sector")),
        geography=_geography(payload.get("Country")),
        market_cap=_num(payload.get("MarketCapitalization")),
        beta=_num(payload.get("Beta")),
        pe=_num(payload.get("PERatio")),
        pb=_num(payload.get("PriceToBookRatio")),
        roe=_num(payload.get("ReturnOnEquityTTM")),
        momentum=momentum,
    )


def map_etf_profile(payload: dict) -> list[ETFConstituent]:
    """The ``holdings`` array of an ``ETF_PROFILE`` response.

    Coverage is partial for broad funds — VT returns its top ~314 of ~9,000
    names — so weights sum to less than 1. The engine handles the remainder.
    """
    out: list[ETFConstituent] = []
    for row in payload.get("holdings") or []:
        ticker = (row.get("symbol") or "").strip()
        weight = _num(row.get("weight"))
        if not ticker or ticker.lower() in _BLANKS or weight is None or weight <= 0:
            continue
        out.append(ETFConstituent(ticker=ticker.upper(), weight=weight))
    return out


def map_daily(payload: dict) -> list[tuple[date, float]]:
    """``TIME_SERIES_DAILY`` as dated closes, oldest first."""
    series = payload.get("Time Series (Daily)") or {}
    out: list[tuple[date, float]] = []
    for day, bar in series.items():
        close = _num(bar.get("4. close"))
        if close is None or close <= 0:
            continue
        try:
            parsed = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            continue
        out.append((parsed, close))
    out.sort(key=lambda pair: pair[0])
    return out


# ---- HTTP --------------------------------------------------------------------

def _get(params: dict) -> dict:
    """One Alpha Vantage call. Raises only on transport failure."""
    settings = get_settings()
    if not settings.alphavantage_configured:
        raise AlphaVantageNotConfigured("ALPHAVANTAGE_API_KEY is not set.")

    import httpx

    query = {**params, "apikey": settings.alphavantage_api_key}
    response = httpx.get(_BASE, params=query, timeout=30.0)
    response.raise_for_status()
    payload = response.json()

    # Throttling and quota exhaustion both arrive as HTTP 200 with a note.
    for key in ("Note", "Information", "Error Message"):
        if key in payload:
            logger.warning("Alpha Vantage %s: %s", key, payload[key])
    return payload


def fetch_overview(ticker: str) -> dict:
    return _get({"function": "OVERVIEW", "symbol": ticker})


def fetch_etf_profile(ticker: str) -> dict:
    return _get({"function": "ETF_PROFILE", "symbol": ticker})


def fetch_daily(ticker: str) -> dict:
    return _get(
        {"function": "TIME_SERIES_DAILY", "symbol": ticker, "outputsize": "compact"}
    )


def is_throttled(payload: dict) -> bool:
    """True when a 200 response means "you've asked too often".

    Only ``Note`` and ``Information`` mean that. ``Error Message`` means the
    *call* was invalid — usually a symbol Alpha Vantage doesn't carry — and
    treating that as a rate limit stops a whole refresh over one bad ticker.
    """
    return any(key in payload for key in ("Note", "Information"))


def has_error(payload: dict) -> bool:
    """True when Alpha Vantage rejected the request itself."""
    return "Error Message" in payload
