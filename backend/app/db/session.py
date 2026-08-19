"""SQLAlchemy engine/session wiring.

SQLite by default so the prototype has zero external dependencies; swap
``DATABASE_URL`` for Postgres without touching call sites.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

_settings = get_settings()

# check_same_thread is a SQLite-only quirk: FastAPI serves requests from a
# thread pool, so the connection must be shareable across threads.
_connect_args = (
    {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(_settings.database_url, connect_args=_connect_args, future=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

Base = declarative_base()


def init_db() -> None:
    """Create any missing tables. Idempotent — safe to call on every startup."""
    from app.db import tables  # noqa: F401  (import registers the ORM models)

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
