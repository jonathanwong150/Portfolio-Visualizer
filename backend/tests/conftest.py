"""Shared pytest fixtures — throwaway in-memory databases."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import tables  # noqa: F401  (import registers the ORM models)
from app.db.session import Base, get_db
from app.main import app


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


@pytest.fixture
def client(monkeypatch, session_factory: sessionmaker) -> Iterator[TestClient]:
    """API client on a throwaway database, with Plaid forced unconfigured.

    Pinning ``plaid_configured`` keeps results identical whether or not the
    developer running the suite has credentials in their local ``.env``.
    """
    monkeypatch.setattr(Settings, "plaid_configured", property(lambda self: False))

    def _override_get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
