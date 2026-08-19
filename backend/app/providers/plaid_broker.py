"""Plaid-backed broker adapter and thin wrappers over the Plaid Investments API.

The adapter never talks to Plaid on the read path — holdings are served from the
snapshot the sync service persisted (see :mod:`app.services.sync`). When Plaid
isn't configured and nothing has been synced yet, it falls back to the injected
adapter (``MockBroker`` in practice) so the prototype always renders.

``plaid`` is imported lazily inside each helper so the package stays optional.
"""
from __future__ import annotations

import logging

from app.config import get_settings
from app.models import Holding
from app.plaid_mapping import map_account_type
from app.providers.base import BrokerAdapter
from app.providers.db_broker import DbBroker

logger = logging.getLogger(__name__)

_PLAID_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


class PlaidBroker(BrokerAdapter):
    """Reads the latest synced snapshot, with a mock fallback when unconfigured."""

    def __init__(self, session_factory=None, fallback: BrokerAdapter | None = None) -> None:
        if session_factory is None:
            from app.db.session import SessionLocal, init_db

            # Idempotent: keeps the adapter usable outside the app lifespan
            # (scripts, workers) where startup hasn't created the schema.
            init_db()
            session_factory = SessionLocal
        self._session_factory = session_factory
        self._fallback = fallback

    def get_holdings(self) -> list[Holding]:
        session = self._session_factory()
        try:
            holdings = DbBroker(session).get_holdings()
        finally:
            session.close()

        if holdings:
            return holdings
        if not get_settings().plaid_configured and self._fallback is not None:
            logger.warning("Plaid is not configured and no snapshot exists — using fallback broker.")
            return self._fallback.get_holdings()
        # Configured but never synced: an empty portfolio is the honest answer.
        return []


# ---- Plaid API helpers (lazy imports) ----------------------------------------

def _plaid_client():
    """Build an authenticated Plaid API client.

    Raises ``RuntimeError`` when credentials are missing — callers should guard
    with ``settings.plaid_configured`` first.
    """
    settings = get_settings()
    if not settings.plaid_configured:
        raise RuntimeError("Plaid credentials are not configured.")

    import plaid
    from plaid.api import plaid_api

    host = _PLAID_HOSTS.get(settings.plaid_env.lower(), _PLAID_HOSTS["sandbox"])
    configuration = plaid.Configuration(
        host=host,
        api_key={"clientId": settings.plaid_client_id, "secret": settings.plaid_secret},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def create_link_token(user_id: str = "prototype-user") -> str:
    """Create a Link token the frontend hands to Plaid Link."""
    settings = get_settings()

    from plaid.model.country_code import CountryCode
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.products import Products

    request = LinkTokenCreateRequest(
        client_name="Portfolio Visualizer",
        language="en",
        country_codes=[
            CountryCode(c.strip().upper())
            for c in settings.plaid_country_codes.split(",")
            if c.strip()
        ],
        products=[
            Products(p.strip().lower())
            for p in settings.plaid_products.split(",")
            if p.strip()
        ],
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
        **({"redirect_uri": settings.plaid_redirect_uri} if settings.plaid_redirect_uri else {}),
    )
    response = _plaid_client().link_token_create(request)
    return response["link_token"]


def exchange_public_token(public_token: str) -> tuple[str, str]:
    """Swap a Link ``public_token`` for a durable ``(access_token, item_id)``."""
    from plaid.model.item_public_token_exchange_request import (
        ItemPublicTokenExchangeRequest,
    )

    response = _plaid_client().item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    )
    return response["access_token"], response["item_id"]


def fetch_investments(access_token: str) -> dict:
    """Pull investment holdings for an Item and normalize them.

    Returns ``{"accounts": [...], "holdings": [...]}`` where each account has
    ``plaid_account_id``/``name``/``type`` (an ``AccountType``)/``institution``
    and each holding has ``plaid_account_id``/``ticker``/``name``/``shares``/
    ``cost_basis``.
    """
    from plaid.model.investments_holdings_get_request import (
        InvestmentsHoldingsGetRequest,
    )

    response = _plaid_client().investments_holdings_get(
        InvestmentsHoldingsGetRequest(access_token=access_token)
    )

    securities = {s["security_id"]: s for s in response["securities"]}

    accounts = [
        {
            "plaid_account_id": a["account_id"],
            "name": a.get("official_name") or a.get("name") or a["account_id"],
            "type": map_account_type(
                str(a.get("type")) if a.get("type") is not None else None,
                str(a.get("subtype")) if a.get("subtype") is not None else None,
            ),
            "institution": a.get("institution_name"),
        }
        for a in response["accounts"]
    ]

    holdings = []
    for h in response["holdings"]:
        security = securities.get(h["security_id"], {})
        ticker = security.get("ticker_symbol") or security.get("name")
        if not ticker:
            continue
        holdings.append(
            {
                "plaid_account_id": h["account_id"],
                "ticker": ticker,
                "name": security.get("name") or ticker,
                "shares": float(h.get("quantity") or 0.0),
                "cost_basis": float(h["cost_basis"]) if h.get("cost_basis") is not None else None,
            }
        )

    return {"accounts": accounts, "holdings": holdings}
