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
from app.db.tables import AccountRow, HoldingRow, PlaidItemRow, SecurityRow
from app.models import SecurityType, SyncResult


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
    accounts_synced = 0
    holdings_synced = 0

    for item in items:
        payload = fetch_investments(item.access_token)

        account_ids: dict[str, int] = {}
        for account in payload["accounts"]:
            row = session.execute(
                select(AccountRow).where(
                    AccountRow.plaid_account_id == account["plaid_account_id"]
                )
            ).scalar_one_or_none()
            if row is None:
                row = AccountRow(plaid_account_id=account["plaid_account_id"])
                session.add(row)
            row.name = account["name"]
            row.type = account["type"].value
            row.institution = account.get("institution") or item.institution
            session.flush()
            account_ids[account["plaid_account_id"]] = row.id
            accounts_synced += 1

        for holding in payload["holdings"]:
            account_id = account_ids.get(holding["plaid_account_id"])
            if account_id is None:
                continue
            session.add(
                HoldingRow(
                    account_id=account_id,
                    ticker=holding["ticker"],
                    shares=holding["shares"],
                    cost_basis=holding.get("cost_basis"),
                    snapshot_at=snapshot_at,
                )
            )
            _upsert_security(session, holding["ticker"], holding.get("name"))
            holdings_synced += 1

    session.commit()
    return SyncResult(
        accounts=accounts_synced, holdings=holdings_synced, snapshot_at=snapshot_at
    )


def _upsert_security(session: Session, ticker: str, name: str | None) -> None:
    """Keep the securities table in step with whatever tickers we've seen."""
    from app.providers.factory import get_etf_holdings

    row = session.get(SecurityRow, ticker)
    security_type = (
        SecurityType.etf if get_etf_holdings().is_etf(ticker) else SecurityType.stock
    )
    if row is None:
        session.add(
            SecurityRow(ticker=ticker, name=name or ticker, type=security_type.value)
        )
        return
    row.name = name or row.name
    row.type = security_type.value
