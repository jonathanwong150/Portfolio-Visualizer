"""Domain models shared across providers and the analytics engine."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AccountType(str, Enum):
    brokerage = "brokerage"
    roth = "roth"
    _401k = "401k"


class SecurityType(str, Enum):
    stock = "stock"
    etf = "etf"
    cash = "cash"


class Security(BaseModel):
    """Metadata for a tradable security."""

    ticker: str
    name: str
    type: SecurityType
    sector: str | None = None
    geography: str | None = None
    market_cap: float | None = None  # USD
    beta: float | None = None
    # Fundamentals used by the rule-based factor engine.
    pe: float | None = None          # price / earnings
    pb: float | None = None          # price / book
    roe: float | None = None         # return on equity (quality proxy)
    momentum: float | None = None    # trailing relative return (1.0 = flat)


class ETFConstituent(BaseModel):
    """A single underlying holding within an ETF."""

    ticker: str
    weight: float  # fraction 0..1 of the ETF


class Holding(BaseModel):
    """A position held in a specific account."""

    ticker: str
    shares: float
    account_type: AccountType
    cost_basis: float | None = None


class Portfolio(BaseModel):
    """A user's full set of holdings across accounts."""

    holdings: list[Holding] = Field(default_factory=list)


# ---- Analytics output shapes -------------------------------------------------

class CompanyExposure(BaseModel):
    ticker: str
    name: str
    value: float          # USD of true exposure
    weight: float         # fraction of total portfolio
    direct_value: float   # held directly
    via_etf_value: float  # held through ETFs
    source_etfs: list[str] = Field(default_factory=list)


class BreakdownSlice(BaseModel):
    label: str
    value: float
    weight: float


class PortfolioSummary(BaseModel):
    net_worth: float
    total_invested: float
    num_accounts: int
    num_holdings: int
    allocation_by_account: list[BreakdownSlice]
    allocation_by_asset_type: list[BreakdownSlice]


class RiskMetrics(BaseModel):
    beta: float | None = None
    annualized_volatility: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None


class FactorTilt(BaseModel):
    """A single factor axis expressed as a two-sided tilt.

    ``score`` in [-1, 1]: negative leans to ``low_label``, positive to
    ``high_label`` (e.g. value <-> growth).
    """

    factor: str
    low_label: str
    high_label: str
    score: float
    high_weight: float   # portfolio weight classified toward high_label
    low_weight: float    # portfolio weight classified toward low_label


class CorrelationMatrix(BaseModel):
    tickers: list[str]
    matrix: list[list[float]]


# ---- Accounts & Plaid sync (Phase 3) -----------------------------------------

class AccountSummary(BaseModel):
    """A synced account with its value priced at request time."""

    id: int
    name: str
    type: AccountType
    institution: str | None = None
    value: float
    num_holdings: int
    last_synced_at: datetime | None = None


class AccountsResponse(BaseModel):
    plaid_configured: bool
    accounts: list[AccountSummary] = Field(default_factory=list)


class LinkTokenResponse(BaseModel):
    configured: bool
    link_token: str | None = None


class ExchangeRequest(BaseModel):
    public_token: str


class SyncResult(BaseModel):
    accounts: int
    holdings: int
    snapshot_at: datetime
