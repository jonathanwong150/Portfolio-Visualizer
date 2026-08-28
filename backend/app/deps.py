"""FastAPI dependency wiring for the analytics engine."""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.analytics.engine import PortfolioAnalytics
from app.db.session import get_db
from app.providers.factory import get_broker, get_etf_holdings, get_market_data


def get_analytics(db: Session = Depends(get_db)) -> PortfolioAnalytics:
    """Build the engine on the request's session.

    The DB-backed broker and price provider read through this session, so they
    see the caller's transaction — and in tests, the in-memory database the
    `client` fixture injects rather than the developer's real ``portfolio.db``.
    """
    return PortfolioAnalytics(
        broker=get_broker(session=db),
        market=get_market_data(session=db),
        etf=get_etf_holdings(),
    )
