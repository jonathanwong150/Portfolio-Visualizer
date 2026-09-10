"""FastAPI application entrypoint."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.engine import PortfolioAnalytics
from app.analytics.history import net_worth_series
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
    ImportCommitRequest,
    LinkTokenResponse,
    NetWorthHistory,
    ParsedImport,
    PortfolioSummary,
    RiskMetrics,
    SyncResult,
)
from app.providers.db_broker import (
    current_holding_rows,
    latest_account_snapshot_times,
    snapshot_history,
)
from app.providers.factory import get_market_data
from app.services.export import exposure_csv, holdings_csv
from app.services import market_refresh
from app.services.import_csv import UnknownFormat, parse_csv
from app.services.market_refresh import Coverage, RefreshResult
from app.services.snapshot import (
    InvalidSnapshot,
    SnapshotAccount,
    SnapshotHolding,
    write_snapshot,
)
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


@app.get("/portfolio/history", response_model=NetWorthHistory)
def portfolio_history(db: Session = Depends(get_db)) -> NetWorthHistory:
    """Net worth at every stored snapshot, each valued at its own date's prices."""
    market = get_market_data(session=db)
    return NetWorthHistory(
        points=net_worth_series(snapshot_history(db), market),
        prices_synthesized=market.prices_are_synthesized,
    )


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


# ---- Market data (Phase 5) ---------------------------------------------------

@app.post("/market-data/refresh", response_model=RefreshResult)
def market_data_refresh(db: Session = Depends(get_db)) -> RefreshResult:
    """Fetch real prices, fundamentals and ETF constituents for held tickers.

    Paced for Alpha Vantage's free tier, so this takes a few seconds per ticker
    and may need running more than once for a large portfolio.
    """
    try:
        return market_refresh.refresh(db)
    except market_refresh.NotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/market-data/coverage", response_model=Coverage)
def market_data_coverage(db: Session = Depends(get_db)) -> Coverage:
    """How much of the portfolio has real data behind it."""
    return market_refresh.coverage(db)


# ---- CSV import (Phase 5) ----------------------------------------------------

_TEMPLATE_CSV = (
    "ticker,shares,account,cost_basis\n"
    "NVDA,40,Individual,6000\n"
    "VOO,35,Roth IRA,14000\n"
    "SCHD,200,My 401k,15000\n"
)


@app.get("/import/template.csv")
def import_template() -> Response:
    """A minimal canonical layout, for when a broker export isn't available."""
    return _csv_response(_TEMPLATE_CSV, "portfolio-template.csv")


@app.post("/import/preview", response_model=ParsedImport)
async def import_preview(file: UploadFile = File(...)) -> ParsedImport:
    """Parse an upload for review. Writes nothing."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="That file isn't UTF-8 text. Export it as CSV rather than XLSX.",
        ) from exc

    try:
        return parse_csv(text)
    except UnknownFormat as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/import/commit", response_model=SyncResult)
def import_commit(
    payload: ImportCommitRequest, db: Session = Depends(get_db)
) -> SyncResult:
    """Persist a reviewed preview as a new snapshot."""
    if not payload.holdings:
        raise HTTPException(status_code=400, detail="Nothing to import.")

    accounts = [
        SnapshotAccount(name=account.name, account_type=account.account_type)
        for account in payload.accounts
    ]
    holdings = [
        SnapshotHolding(
            account_key=holding.account_name,
            ticker=holding.ticker,
            shares=holding.shares,
            cost_basis=holding.cost_basis,
            name=holding.name,
            security_type=holding.security_type,
            price=holding.price,
        )
        for holding in payload.holdings
    ]
    try:
        return write_snapshot(db, accounts, holdings)
    except InvalidSnapshot as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- CSV export (Phase 4) ----------------------------------------------------

def _csv_response(body: str, filename: str) -> Response:
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/holdings.csv")
def export_holdings(analytics: PortfolioAnalytics = Depends(get_analytics)) -> Response:
    """Raw positions as CSV."""
    return _csv_response(
        holdings_csv(analytics.holdings, analytics.market), "holdings.csv"
    )


@app.get("/export/exposure.csv")
def export_exposure(analytics: PortfolioAnalytics = Depends(get_analytics)) -> Response:
    """True per-company exposure, post look-through, as CSV."""
    return _csv_response(exposure_csv(analytics.company_exposure()), "exposure.csv")


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
    except InvalidSnapshot as exc:
        raise HTTPException(
            status_code=502, detail="Broker holdings did not match the supplied accounts."
        ) from exc


@app.get("/accounts", response_model=AccountsResponse)
def accounts(db: Session = Depends(get_db)) -> AccountsResponse:
    """Synced accounts with their holdings valued at current prices."""
    market = get_market_data(session=db)
    rows = db.execute(select(AccountRow)).scalars().all()
    snapshot_times = latest_account_snapshot_times(db)
    holdings_by_account: dict[int, list[HoldingRow]] = {}
    for holding in current_holding_rows(db):
        holdings_by_account.setdefault(holding.account_id, []).append(holding)

    summaries: list[AccountSummary] = []
    for account in rows:
        last_synced_at = snapshot_times.get(account.id)
        holdings = holdings_by_account.get(account.id, [])
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
