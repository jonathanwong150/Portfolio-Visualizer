"""Domain models shared across providers and the analytics engine."""
from __future__ import annotations

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
