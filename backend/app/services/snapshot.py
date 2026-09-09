"""Writing a holdings snapshot to the database.

Shared by Plaid sync and CSV import: accounts are upserted in place, holdings are
always appended with one shared ``snapshot_at`` so prior snapshots stay intact
for the net-worth history.

Accounts are identified by ``plaid_account_id`` when one exists and by ``name``
otherwise — re-importing the same brokerage file updates its accounts rather
than duplicating them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import AccountRow, AccountSnapshotRow, HoldingRow, SecurityRow
from app.models import AccountType, SecurityType, SyncResult


class InvalidSnapshot(ValueError):
    """A source supplied holdings that cannot be assigned to its accounts."""


@dataclass
class SnapshotAccount:
    name: str
    account_type: AccountType
    institution: str | None = None
    plaid_account_id: str | None = None

    @property
    def key(self) -> str:
        return self.plaid_account_id or self.name


@dataclass
class SnapshotHolding:
    account_key: str
    ticker: str
    shares: float
    cost_basis: float | None = None
    name: str | None = None
    security_type: SecurityType | None = None
    # Per-share price from the source, when it reported one.
    price: float | None = None


def write_snapshot(
    session: Session,
    accounts: list[SnapshotAccount],
    holdings: list[SnapshotHolding],
    snapshot_at: datetime | None = None,
) -> SyncResult:
    """Upsert accounts, append one holdings snapshot, upsert securities."""
    account_keys = {account.key for account in accounts}
    if any(holding.account_key not in account_keys for holding in holdings):
        raise InvalidSnapshot("Every holding must belong to a supplied account.")
    snapshot_at = snapshot_at or datetime.utcnow()
    account_ids: dict[str, int] = {}

    for account in accounts:
        if account.plaid_account_id:
            row = session.execute(
                select(AccountRow).where(
                    AccountRow.plaid_account_id == account.plaid_account_id
                )
            ).scalar_one_or_none()
        else:
            row = session.execute(
                select(AccountRow).where(
                    AccountRow.plaid_account_id.is_(None), AccountRow.name == account.name
                )
            ).scalar_one_or_none()

        if row is None:
            row = AccountRow(plaid_account_id=account.plaid_account_id)
            session.add(row)
        row.name = account.name
        row.type = account.account_type.value
        row.institution = account.institution or row.institution
        session.flush()
        account_ids[account.key] = row.id

    # Holding rows cannot represent an observed empty account, so record every
    # supplied account independently of whether it currently has positions.
    for account_id in set(account_ids.values()):
        session.add(AccountSnapshotRow(account_id=account_id, snapshot_at=snapshot_at))

    written = 0
    for holding in holdings:
        account_id = account_ids[holding.account_key]
        session.add(
            HoldingRow(
                account_id=account_id,
                ticker=holding.ticker,
                shares=holding.shares,
                cost_basis=holding.cost_basis,
                price=holding.price,
                snapshot_at=snapshot_at,
            )
        )
        upsert_security(session, holding.ticker, holding.name, holding.security_type)
        written += 1

    session.commit()
    return SyncResult(accounts=len(account_ids), holdings=written, snapshot_at=snapshot_at)


def upsert_security(
    session: Session,
    ticker: str,
    name: str | None,
    security_type: SecurityType | None = None,
) -> None:
    """Keep the securities table in step with whatever tickers we've seen.

    ``security_type`` overrides detection — CSV import already knows a sweep
    fund is cash, which ``is_etf`` would otherwise call a stock.
    """
    if security_type is None:
        from app.providers.factory import get_etf_holdings

        security_type = (
            SecurityType.etf if get_etf_holdings().is_etf(ticker) else SecurityType.stock
        )

    row = session.get(SecurityRow, ticker)
    if row is None:
        session.add(
            SecurityRow(ticker=ticker, name=name or ticker, type=security_type.value)
        )
        return
    row.name = name or row.name
    row.type = security_type.value
