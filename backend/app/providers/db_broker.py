"""Broker adapter that reads account-scoped holdings snapshots from the database."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select, tuple_, union_all
from sqlalchemy.orm import Session

from app.db.tables import AccountRow, AccountSnapshotRow, HoldingRow
from app.models import AccountType, Holding
from app.providers.base import BrokerAdapter


def latest_account_snapshot_times(session: Session) -> dict[int, datetime]:
    """Latest observed timestamp per account, including legacy unmarked data."""
    events = union_all(
        select(AccountSnapshotRow.account_id, AccountSnapshotRow.snapshot_at),
        select(HoldingRow.account_id, HoldingRow.snapshot_at),
    ).subquery()
    return dict(
        session.execute(
            select(events.c.account_id, func.max(events.c.snapshot_at)).group_by(
                events.c.account_id
            )
        ).all()
    )


def latest_snapshot_at(session: Session) -> datetime | None:
    """Timestamp of the most recent account update, including empty updates."""
    return max(latest_account_snapshot_times(session).values(), default=None)


def current_holding_rows(session: Session) -> list[HoldingRow]:
    """Holding rows from each account's latest observed snapshot."""
    latest = latest_account_snapshot_times(session)
    if not latest:
        return []
    return list(
        session.execute(
            select(HoldingRow)
            .where(
                tuple_(HoldingRow.account_id, HoldingRow.snapshot_at).in_(
                    list(latest.items())
                )
            )
            .order_by(HoldingRow.account_id, HoldingRow.id)
        )
        .scalars()
        .all()
    )


def _to_holding(holding: HoldingRow, account: AccountRow) -> Holding:
    return Holding(
        ticker=holding.ticker,
        shares=holding.shares,
        account_type=AccountType(account.type),
        cost_basis=holding.cost_basis,
    )


def snapshot_history(session: Session) -> list[tuple[datetime, list[Holding]]]:
    """Complete portfolio state after every account update, oldest first.

    Snapshot markers make empty updates visible. Holding timestamps are unioned
    in so databases created before markers existed remain readable as-is.
    """
    accounts = {
        account.id: account
        for account in session.execute(select(AccountRow)).scalars().all()
    }
    rows = list(
        session.execute(
            select(HoldingRow).order_by(
                HoldingRow.snapshot_at, HoldingRow.account_id, HoldingRow.id
            )
        )
        .scalars()
        .all()
    )
    holdings_by_update: dict[tuple[int, datetime], list[HoldingRow]] = defaultdict(list)
    accounts_by_update: dict[datetime, set[int]] = defaultdict(set)
    for holding in rows:
        holdings_by_update[(holding.account_id, holding.snapshot_at)].append(holding)
        accounts_by_update[holding.snapshot_at].add(holding.account_id)
    for account_id, snapshot_at in session.execute(
        select(AccountSnapshotRow.account_id, AccountSnapshotRow.snapshot_at)
    ):
        accounts_by_update[snapshot_at].add(account_id)

    current: dict[int, list[Holding]] = {}
    history: list[tuple[datetime, list[Holding]]] = []
    for snapshot_at in sorted(accounts_by_update):
        for account_id in accounts_by_update[snapshot_at]:
            account = accounts[account_id]
            current[account_id] = [
                _to_holding(holding, account)
                for holding in holdings_by_update[(account_id, snapshot_at)]
            ]
        portfolio = [
            holding
            for account_id in sorted(current)
            for holding in current[account_id]
        ]
        history.append((snapshot_at, portfolio))
    return history


class DbBroker(BrokerAdapter):
    """Serves holdings from each account's newest snapshot."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_holdings(self) -> list[Holding]:
        accounts = {
            account.id: account
            for account in self._session.execute(select(AccountRow)).scalars().all()
        }
        return [
            _to_holding(holding, accounts[holding.account_id])
            for holding in current_holding_rows(self._session)
        ]
