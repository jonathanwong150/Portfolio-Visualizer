"""API-level tests for the Phase 3 endpoints with Plaid intentionally unconfigured."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.session import get_db
from app.main import app


@pytest.fixture
def client(monkeypatch, session_factory):
    monkeypatch.setattr(Settings, "plaid_configured", property(lambda self: False))

    def _override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_link_reports_unconfigured_instead_of_erroring(client):
    res = client.post("/plaid/link")
    assert res.status_code == 200
    assert res.json() == {"configured": False, "link_token": None}


def test_accounts_is_empty_and_flags_unconfigured(client):
    res = client.get("/accounts")
    assert res.status_code == 200
    body = res.json()
    assert body["plaid_configured"] is False
    assert body["accounts"] == []


def test_sync_returns_409_not_500(client):
    res = client.post("/plaid/sync")
    assert res.status_code == 409


def test_exchange_returns_409_when_unconfigured(client):
    res = client.post("/plaid/exchange", json={"public_token": "public-sandbox-1"})
    assert res.status_code == 409


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/portfolio/summary",
        "/exposure/companies",
        "/exposure/sectors",
        "/exposure/geography",
        "/exposure/factors",
        "/overlap",
        "/risk/metrics",
        "/risk/correlation",
    ],
)
def test_existing_endpoints_still_serve(client, path):
    assert client.get(path).status_code == 200
