"""Consolidation across independently imported and synced accounts."""
from __future__ import annotations

import csv
import io
from datetime import datetime

import pytest

from app.config import Settings, get_settings
from app.db.tables import AccountRow, AccountSnapshotRow, PlaidItemRow
from app.models import AccountType


@pytest.fixture(autouse=True)
def use_stored_portfolio(monkeypatch):
    monkeypatch.setattr(get_settings(), "broker_provider", "db")
    monkeypatch.setattr(get_settings(), "market_provider", "seed")
    monkeypatch.setattr(get_settings(), "etf_provider", "seed")


def _import(client, account, ticker, shares, price):
    response = client.post(
        "/import/commit",
        json={
            "accounts": [{"name": account, "account_type": "brokerage"}],
            "holdings": [{
                "account_name": account, "ticker": ticker,
                "shares": shares, "price": price,
            }],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["holdings"] == 1
    return response.json()["snapshot_at"]


def _assert_portfolio(client, expected_values):
    expected_total = sum(expected_values.values())
    summary = client.get("/portfolio/summary").json()
    assert summary["net_worth"] == pytest.approx(expected_total)
    accounts = client.get("/accounts").json()["accounts"]
    assert summary["num_accounts"] == len(accounts)
    assert sum(a["value"] for a in accounts) == pytest.approx(expected_total)
    exposures = client.get("/exposure/companies").json()
    assert {e["ticker"]: e["value"] for e in exposures} == pytest.approx(expected_values)
    exported = list(csv.DictReader(io.StringIO(client.get("/export/holdings.csv").text)))
    assert {h["ticker"] for h in exported} == set(expected_values)
    assert sum(float(h["value"]) for h in exported) == pytest.approx(expected_total)
    coverage = client.get("/market-data/coverage").json()
    assert coverage["total_tickers"] == len(expected_values)
    assert set(coverage["missing"]) == set(expected_values)


def test_summary_marks_a_fresh_db_portfolio_as_demo(client):
    assert client.get("/portfolio/summary").json()["data_status"] == "demo"


def test_summary_marks_saved_and_mixed_portfolios_as_stored(
    client, monkeypatch, session_factory,
):
    _import(client, "CSV Brokerage", "NVDA", 2, 100)
    _linked_account(monkeypatch, session_factory)
    assert client.post("/plaid/sync").status_code == 200

    assert client.get("/portfolio/summary").json()["data_status"] == "stored"


def test_summary_keeps_a_cleared_portfolio_stored(client, session_factory):
    with session_factory() as session:
        account = AccountRow(name="Closed Account", type="brokerage")
        session.add(account)
        session.flush()
        session.add(
            AccountSnapshotRow(
                account_id=account.id,
                snapshot_at=datetime(2026, 9, 9, 12),
            )
        )
        session.commit()

    summary = client.get("/portfolio/summary").json()
    assert summary["data_status"] == "stored"
    assert summary["net_worth"] == 0


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(True, "empty"), (False, "demo")],
)
def test_summary_distinguishes_configured_plaid_before_first_sync(
    client, monkeypatch, configured, expected,
):
    monkeypatch.setattr(get_settings(), "broker_provider", "plaid")
    monkeypatch.setattr(
        Settings,
        "plaid_configured",
        property(lambda self: configured),
    )

    assert client.get("/portfolio/summary").json()["data_status"] == expected


def test_configured_mock_provider_stays_demo_even_with_saved_holdings(
    client, monkeypatch,
):
    _import(client, "CSV Brokerage", "NVDA", 2, 100)
    monkeypatch.setattr(get_settings(), "broker_provider", "mock")

    summary = client.get("/portfolio/summary").json()
    assert summary["data_status"] == "demo"
    assert summary["net_worth"] != 200


def test_separate_imports_and_account_replacement_reconcile_every_view(client):
    first = _import(client, "Brokerage", "NVDA", 10, 100)
    _assert_portfolio(client, {"NVDA": 1000})
    second = _import(client, "Retirement", "AAPL", 5, 200)
    _assert_portfolio(client, {"NVDA": 1000, "AAPL": 1000})
    third = _import(client, "Brokerage", "MSFT", 2, 300)
    _assert_portfolio(client, {"MSFT": 600, "AAPL": 1000})

    points = client.get("/portfolio/history").json()["points"]
    assert [p["snapshot_at"] for p in points] == [first, second, third]
    assert [p["net_worth"] for p in points] == pytest.approx([1000, 2000, 1600])
    assert [p["num_holdings"] for p in points] == [1, 2, 2]
    by_name = {a["name"]: a for a in client.get("/accounts").json()["accounts"]}
    assert by_name["Retirement"]["last_synced_at"] == second
    assert by_name["Brokerage"]["last_synced_at"] == third


def test_import_with_unmatched_account_is_rejected_without_clearing_holdings(client):
    _import(client, "Brokerage", "NVDA", 10, 100)
    response = client.post(
        "/import/commit",
        json={
            "accounts": [{"name": "Brokerage", "account_type": "brokerage"}],
            "holdings": [{
                "account_name": "Unmatched", "ticker": "AAPL", "shares": 5,
            }],
        },
    )
    assert response.status_code == 400
    _assert_portfolio(client, {"NVDA": 1000})
    assert len(client.get("/portfolio/history").json()["points"]) == 1


def _linked_account(monkeypatch, session_factory):
    monkeypatch.setattr(Settings, "plaid_configured", property(lambda self: True))
    with session_factory() as session:
        session.add(PlaidItemRow(access_token="test-token", item_id="test-item"))
        session.commit()
    payload = {
        "accounts": [{
            "plaid_account_id": "linked-roth", "name": "Linked Roth",
            "type": AccountType.roth,
        }],
        "holdings": [{
            "plaid_account_id": "linked-roth", "ticker": "NVDA", "shares": 3,
        }],
    }
    monkeypatch.setattr("app.providers.plaid_broker.fetch_investments", lambda _: payload)
    return payload


def test_csv_and_plaid_accounts_survive_updates_in_both_directions(
    client, monkeypatch, session_factory,
):
    _import(client, "CSV Brokerage", "NVDA", 2, 100)
    _linked_account(monkeypatch, session_factory)
    response = client.post("/plaid/sync")
    assert response.status_code == 200, response.text
    _assert_portfolio(client, {"NVDA": 500})

    _import(client, "CSV Brokerage", "AAPL", 4, 200)
    _assert_portfolio(client, {"NVDA": 300, "AAPL": 800})
    points = client.get("/portfolio/history").json()["points"]
    assert [p["net_worth"] for p in points] == pytest.approx([200, 500, 1100])


def test_empty_plaid_update_clears_only_that_account(client, monkeypatch, session_factory):
    _import(client, "CSV Brokerage", "NVDA", 2, 100)
    payload = _linked_account(monkeypatch, session_factory)
    assert client.post("/plaid/sync").status_code == 200
    payload["holdings"] = []
    response = client.post("/plaid/sync")
    assert response.status_code == 200, response.text
    assert response.json()["holdings"] == 0
    _assert_portfolio(client, {"NVDA": 200})
    linked = next(a for a in client.get("/accounts").json()["accounts"] if a["name"] == "Linked Roth")
    assert linked["value"] == 0
    assert linked["num_holdings"] == 0
    assert linked["last_synced_at"] == response.json()["snapshot_at"]
    assert [p["net_worth"] for p in client.get("/portfolio/history").json()["points"]] == pytest.approx([200, 500, 200])


def test_mismatched_plaid_holdings_are_rejected_without_clearing_accounts(
    client, monkeypatch, session_factory,
):
    _import(client, "CSV Brokerage", "NVDA", 2, 100)
    payload = _linked_account(monkeypatch, session_factory)
    assert client.post("/plaid/sync").status_code == 200
    payload["holdings"][0]["plaid_account_id"] = "unmatched-account"
    response = client.post("/plaid/sync")
    assert response.status_code == 502
    _assert_portfolio(client, {"NVDA": 500})
    assert len(client.get("/portfolio/history").json()["points"]) == 2


def test_clearing_final_account_keeps_portfolio_empty_instead_of_showing_demo(
    client, monkeypatch, session_factory,
):
    payload = _linked_account(monkeypatch, session_factory)
    assert client.post("/plaid/sync").status_code == 200
    payload["holdings"] = []
    assert client.post("/plaid/sync").status_code == 200
    _assert_portfolio(client, {})
    points = client.get("/portfolio/history").json()["points"]
    assert len(points) == 2
    assert points[-1]["net_worth"] == 0
    assert points[-1]["num_holdings"] == 0
