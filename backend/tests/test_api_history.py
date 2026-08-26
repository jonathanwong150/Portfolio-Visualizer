"""API-level tests for GET /portfolio/history."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.db.tables import AccountRow, HoldingRow
from app.models import AccountType
from app.providers.seed import SeedMarketDataProvider


def _seed_two_snapshots(session_factory) -> tuple[datetime, datetime]:
    """Two snapshots a month apart; the second adds shares."""
    older = datetime.now().replace(microsecond=0) - timedelta(days=30)
    newer = datetime.now().replace(microsecond=0) - timedelta(days=1)

    db = session_factory()
    try:
        account = AccountRow(name="Brokerage", type=AccountType.brokerage.value)
        db.add(account)
        db.flush()
        db.add_all(
            [
                HoldingRow(account_id=account.id, ticker="NVDA", shares=10, snapshot_at=older),
                HoldingRow(account_id=account.id, ticker="NVDA", shares=15, snapshot_at=newer),
                HoldingRow(account_id=account.id, ticker="VOO", shares=4, snapshot_at=newer),
            ]
        )
        db.commit()
    finally:
        db.close()
    return older, newer


def test_history_is_empty_on_a_fresh_database(client):
    res = client.get("/portfolio/history")
    assert res.status_code == 200
    body = res.json()
    assert body["points"] == []
    # The flag must be present even with no points, so the UI can caption it.
    assert body["prices_synthesized"] is True


def test_history_returns_one_point_per_snapshot_oldest_first(client, session_factory):
    older, newer = _seed_two_snapshots(session_factory)

    body = client.get("/portfolio/history").json()

    assert [p["num_holdings"] for p in body["points"]] == [1, 2]
    assert [p["snapshot_at"] for p in body["points"]] == [
        older.isoformat(),
        newer.isoformat(),
    ]


def test_history_values_match_the_provider_at_each_snapshot_date(client, session_factory):
    older, newer = _seed_two_snapshots(session_factory)
    market = SeedMarketDataProvider()

    points = client.get("/portfolio/history").json()["points"]

    expected_older = 10 * market.get_price_on("NVDA", older.date())
    expected_newer = 15 * market.get_price_on("NVDA", newer.date()) + 4 * market.get_price_on(
        "VOO", newer.date()
    )
    assert points[0]["net_worth"] == expected_older
    assert points[1]["net_worth"] == expected_newer
    # Prices differ by date, so the two points must not coincidentally match.
    assert points[0]["net_worth"] != points[1]["net_worth"]


def test_history_reports_synthesized_prices_while_the_seed_provider_is_in_use(client):
    assert client.get("/portfolio/history").json()["prices_synthesized"] is True
