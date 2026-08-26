"""ORM tables backing the Plaid sync and multi-account aggregation.

Holdings are stored as immutable **snapshots**: every sync writes a fresh set of
rows sharing one ``snapshot_at``, so history is preserved and the current
portfolio is simply "all rows at max(snapshot_at)".

``AccountRow.type`` stores the ``AccountType`` *value* (``"401k"``, not the
Python member name ``_401k``); reconstruct with ``AccountType(row.type)``.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)


class AccountRow(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    plaid_account_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # AccountType.value
    institution: Mapped[str | None] = mapped_column(String, nullable=True)

    holdings: Mapped[list[HoldingRow]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class HoldingRow(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    cost_basis: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)

    account: Mapped[AccountRow] = relationship(back_populates="holdings")


class SecurityRow(Base):
    __tablename__ = "securities"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # SecurityType.value


class PlaidItemRow(Base):
    __tablename__ = "plaid_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    institution: Mapped[str | None] = mapped_column(String, nullable=True)
