"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.analytics.engine import PortfolioAnalytics
from app.config import get_settings
from app.deps import get_analytics
from app.models import (
    BreakdownSlice,
    CompanyExposure,
    CorrelationMatrix,
    FactorTilt,
    PortfolioSummary,
    RiskMetrics,
)

settings = get_settings()

app = FastAPI(
    title="Portfolio Visualizer API",
    version="0.1.0",
    description="ETF look-through and portfolio risk analytics.",
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
