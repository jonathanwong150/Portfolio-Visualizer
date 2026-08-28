"""Plaid → database sync.

Each run writes one immutable snapshot: accounts are upserted in place, while
holdings are always appended with a shared ``snapshot_at`` so prior snapshots
stay intact for historical comparisons.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.tables import PlaidItemRow
from app.models import SyncResult
from app.services.snapshot import SnapshotAccount, SnapshotHolding, write_snapshot


class PlaidNotConfigured(Exception):
    """Raised when a sync is requested without credentials or linked items."""


def sync_holdings(session: Session) -> SyncResult:
    """Refresh holdings for every linked Plaid Item.

    Raises ``PlaidNotConfigured`` when credentials are missing or no Item has
    been linked yet — the API layer turns that into a 409.
    """
    if not get_settings().plaid_configured:
        raise PlaidNotConfigured("Plaid credentials are not configured.")

    items = session.execute(select(PlaidItemRow)).scalars().all()
    if not items:
        raise PlaidNotConfigured("No Plaid items linked — connect an account first.")

    from app.providers.plaid_broker import fetch_investments

    snapshot_at = datetime.utcnow()
    accounts: list[SnapshotAccount] = []
    holdings: list[SnapshotHolding] = []

    for item in items:
        payload = fetch_investments(item.access_token)

        accounts.extend(
            SnapshotAccount(
                name=account["name"],
                account_type=account["type"],
                institution=account.get("institution") or item.institution,
                plaid_account_id=account["plaid_account_id"],
            )
            for account in payload["accounts"]
        )
        holdings.extend(
            SnapshotHolding(
                account_key=holding["plaid_account_id"],
                ticker=holding["ticker"],
                shares=holding["shares"],
                cost_basis=holding.get("cost_basis"),
                name=holding.get("name"),
            )
            for holding in payload["holdings"]
        )

    return write_snapshot(session, accounts, holdings, snapshot_at)
