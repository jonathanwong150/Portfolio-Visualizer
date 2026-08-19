"""Shared pytest fixtures — throwaway in-memory databases."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import tables  # noqa: F401  (import registers the ORM models)
from app.db.session import Base


@pytest.fixture
def session_factory() -> Iterator[sessionmaker]:
    """A sessionmaker bound to a fresh in-memory SQLite database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    engine.dispose()


@pytest.fixture
def session(session_factory: sessionmaker) -> Iterator[Session]:
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
