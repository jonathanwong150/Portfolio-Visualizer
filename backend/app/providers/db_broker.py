"""Broker adapter that reads the latest holdings snapshot out of the database."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tables import AccountRow, HoldingRow
from app.models import AccountType, Holding
from app.providers.base import BrokerAdapter


def latest_snapshot_at(session: Session) -> datetime | None:
    """Timestamp of the most recent sync, or ``None`` when nothing is stored."""
    return session.execute(select(func.max(HoldingRow.snapshot_at))).scalar_one_or_none()


class DbBroker(BrokerAdapter):
    """Serves holdings from the newest snapshot written by the sync service."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_holdings(self) -> list[Holding]:
        snapshot_at = latest_snapshot_at(self._session)
        if snapshot_at is None:
            return []
        rows = (
            self._session.execute(
                select(HoldingRow, AccountRow)
                .join(AccountRow, AccountRow.id == HoldingRow.account_id)
                .where(HoldingRow.snapshot_at == snapshot_at)
            )
            .all()
        )
        return [
            Holding(
                ticker=holding.ticker,
                shares=holding.shares,
                account_type=AccountType(account.type),
                cost_basis=holding.cost_basis,
            )
            for holding, account in rows
        ]
