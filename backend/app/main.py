"""FastAPI application entrypoint."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.engine import PortfolioAnalytics
from app.config import get_settings
from app.db.session import get_db, init_db
from app.db.tables import AccountRow, HoldingRow, PlaidItemRow
from app.deps import get_analytics
from app.models import (
    AccountsResponse,
    AccountSummary,
    AccountType,
    BreakdownSlice,
    CompanyExposure,
    CorrelationMatrix,
    ExchangeRequest,
    FactorTilt,
    LinkTokenResponse,
    PortfolioSummary,
    RiskMetrics,
    SyncResult,
)
from app.providers.factory import get_market_data
from app.services.sync import PlaidNotConfigured, sync_holdings

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Ensure the SQLite schema exists before serving traffic."""
    init_db()
    yield


app = FastAPI(
    title="Portfolio Visualizer API",
    version="0.1.0",
    description="ETF look-through and portfolio risk analytics.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/portfolio/summary", response_model=PortfolioSummary)
def portfolio_summary(
    analytics: PortfolioAnalytics = Depends(get_analytics),
) -> PortfolioSummary:
    return analytics.summary()


@app.get("/exposure/companies", response_model=list[CompanyExposure])
def exposure_companies(
    analytics: PortfolioAnalytics = Depends(get_analytics),
) -> list[CompanyExposure]:
    return analytics.company_exposure()


@app.get("/exposure/sectors", response_model=list[BreakdownSlice])
def exposure_sectors(
    analytics: PortfolioAnalytics = Depends(get_analytics),
) -> list[BreakdownSlice]:
    return analytics.sector_breakdown()


@app.get("/exposure/geography", response_model=list[BreakdownSlice])
def exposure_geography(
    analytics: PortfolioAnalytics = Depends(get_analytics),
) -> list[BreakdownSlice]:
    return analytics.geography_breakdown()


@app.get("/overlap")
def overlap(
    analytics: PortfolioAnalytics = Depends(get_analytics),
) -> dict:
    return analytics.etf_overlap()


@app.get("/exposure/factors", response_model=list[FactorTilt])
def exposure_factors(
    analytics: PortfolioAnalytics = Depends(get_analytics),
) -> list[FactorTilt]:
    return analytics.factor_tilts()


@app.get("/risk/correlation", response_model=CorrelationMatrix)
def risk_correlation(
    analytics: PortfolioAnalytics = Depends(get_analytics),
) -> CorrelationMatrix:
    return analytics.correlation_matrix()


@app.get("/risk/metrics", response_model=RiskMetrics)
def risk_metrics(
    analytics: PortfolioAnalytics = Depends(get_analytics),
) -> RiskMetrics:
    return analytics.risk_metrics()


# ---- Accounts & Plaid sync (Phase 3) -----------------------------------------

@app.post("/plaid/link", response_model=LinkTokenResponse)
def plaid_link() -> LinkTokenResponse:
    """Mint a Link token. Reports ``configured=false`` instead of erroring."""
    if not get_settings().plaid_configured:
        return LinkTokenResponse(configured=False)
    from app.providers.plaid_broker import create_link_token

    return LinkTokenResponse(configured=True, link_token=create_link_token())


@app.post("/plaid/exchange")
def plaid_exchange(
    payload: ExchangeRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Exchange a Link ``public_token`` and persist the resulting Item."""
    if not get_settings().plaid_configured:
        raise HTTPException(status_code=409, detail="Plaid is not configured.")
    from app.providers.plaid_broker import exchange_public_token

    access_token, item_id = exchange_public_token(payload.public_token)
    db.add(PlaidItemRow(access_token=access_token, item_id=item_id))
    db.commit()
    return {"item_id": item_id}


@app.post("/plaid/sync", response_model=SyncResult)
def plaid_sync(db: Session = Depends(get_db)) -> SyncResult:
    try:
        return sync_holdings(db)
    except PlaidNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/accounts", response_model=AccountsResponse)
def accounts(db: Session = Depends(get_db)) -> AccountsResponse:
    """Synced accounts with their holdings valued at current prices."""
    market = get_market_data()
    rows = db.execute(select(AccountRow)).scalars().all()

    summaries: list[AccountSummary] = []
    for account in rows:
        last_synced_at = db.execute(
            select(func.max(HoldingRow.snapshot_at)).where(
                HoldingRow.account_id == account.id
            )
        ).scalar_one_or_none()
        holdings = (
            db.execute(
                select(HoldingRow).where(
                    HoldingRow.account_id == account.id,
                    HoldingRow.snapshot_at == last_synced_at,
                )
            )
            .scalars()
            .all()
            if last_synced_at is not None
            else []
        )
        summaries.append(
            AccountSummary(
                id=account.id,
                name=account.name,
                type=AccountType(account.type),
                institution=account.institution,
                value=sum(h.shares * market.get_price(h.ticker) for h in holdings),
                num_holdings=len(holdings),
                last_synced_at=last_synced_at,
            )
        )

    return AccountsResponse(
        plaid_configured=get_settings().plaid_configured, accounts=summaries
    )
