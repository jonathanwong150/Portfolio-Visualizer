"""Tests for net-worth history over holdings snapshots."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app.analytics.history import net_worth_series
from app.db.tables import AccountRow, AccountSnapshotRow, HoldingRow
from app.models import AccountType, Holding
from app.providers.base import MarketDataProvider
from app.providers.db_broker import snapshot_history
from app.providers.seed import SeedMarketDataProvider


class FixedPriceMarket(MarketDataProvider):
    """Prices keyed by (ticker, date) so expected values are hand-computable."""

    def __init__(self, prices: dict[tuple[str, date], float]) -> None:
        self._prices = prices

    def get_security(self, ticker: str):  # pragma: no cover - unused here
        return None

    def get_price_history(self, ticker: str) -> list[float]:  # pragma: no cover
        return []

    def get_price_on(self, ticker: str, on: date) -> float:
        return self._prices.get((ticker, on), 0.0)


class NoHistoryMarket(MarketDataProvider):
    """Exercises the ``get_price_on`` default with nothing to index into."""

    def get_security(self, ticker: str):  # pragma: no cover - unused here
        return None

    def get_price_history(self, ticker: str) -> list[float]:
        return []


def _account(session, type_: AccountType = AccountType.brokerage) -> AccountRow:
    row = AccountRow(name="Test Account", type=type_.value, institution="Test Bank")
    session.add(row)
    session.flush()
    return row


# ---- get_price_on ------------------------------------------------------------

def test_price_on_today_matches_the_latest_close():
    market = SeedMarketDataProvider()
    assert market.get_price_on("NVDA", date.today()) == market.get_price("NVDA")


def test_price_on_walks_back_through_the_series():
    market = SeedMarketDataProvider()
    series = market.get_price_history("NVDA")

    assert market.get_price_on("NVDA", date.today() - timedelta(days=1)) == series[-2]
    assert market.get_price_on("NVDA", date.today() - timedelta(days=10)) == series[-11]


def test_price_on_clamps_past_both_ends_of_the_series():
    market = SeedMarketDataProvider()
    series = market.get_price_history("NVDA")

    # Older than the series -> oldest close we have.
    assert market.get_price_on("NVDA", date.today() - timedelta(days=5000)) == series[0]
    # A future date can't have a close; the latest is the honest answer.
    assert market.get_price_on("NVDA", date.today() + timedelta(days=30)) == series[-1]


def test_price_on_is_zero_when_there_is_no_price_history():
    market = NoHistoryMarket()
    assert market.get_price_on("NOPE", date.today()) == 0.0
    assert market.get_price_on("NOPE", date.today() - timedelta(days=90)) == 0.0


def test_seed_provider_declares_its_prices_synthesized():
    assert SeedMarketDataProvider.prices_are_synthesized is True
    # The interface default must stay False so a real provider isn't mislabelled.
    assert MarketDataProvider.prices_are_synthesized is False


# ---- snapshot_history -------------------------------------------------------

def test_snapshot_history_is_empty_for_an_empty_database(session):
    assert snapshot_history(session) == []


def test_snapshot_history_groups_by_timestamp_oldest_first(session):
    account = _account(session)
    older = datetime(2024, 1, 1, 12, 0, 0)
    newer = datetime(2024, 2, 1, 12, 0, 0)
    session.add_all(
        [
            HoldingRow(account_id=account.id, ticker="SPY", shares=3, snapshot_at=newer),
            HoldingRow(account_id=account.id, ticker="NVDA", shares=10, snapshot_at=older),
            HoldingRow(account_id=account.id, ticker="AAPL", shares=5, snapshot_at=older),
        ]
    )
    session.commit()

    history = snapshot_history(session)
    assert [at for at, _ in history] == [older, newer]
    assert sorted(h.ticker for h in history[0][1]) == ["AAPL", "NVDA"]
    assert [h.ticker for h in history[1][1]] == ["SPY"]


def test_snapshot_history_reconstructs_account_type_and_cost_basis(session):
    retirement = _account(session, AccountType._401k)
    at = datetime(2024, 3, 1, 9, 30, 0)
    session.add(
        HoldingRow(
            account_id=retirement.id, ticker="VOO", shares=35, cost_basis=9000, snapshot_at=at
        )
    )
    session.commit()

    (_, holdings), = snapshot_history(session)
    assert holdings[0].account_type is AccountType._401k
    assert holdings[0].cost_basis == 9000


def test_snapshot_history_reconstructs_complete_portfolio_at_each_account_update(session):
    taxable = _account(session)
    roth = _account(session, AccountType.roth)
    jan = datetime(2024, 1, 1)
    feb = datetime(2024, 2, 1)
    march = datetime(2024, 3, 1)
    session.add_all(
        [
            AccountSnapshotRow(account_id=taxable.id, snapshot_at=jan),
            HoldingRow(account_id=taxable.id, ticker="NVDA", shares=10, snapshot_at=jan),
            AccountSnapshotRow(account_id=roth.id, snapshot_at=feb),
            HoldingRow(account_id=roth.id, ticker="VTI", shares=5, snapshot_at=feb),
            AccountSnapshotRow(account_id=taxable.id, snapshot_at=march),
            HoldingRow(account_id=taxable.id, ticker="AAPL", shares=4, snapshot_at=march),
        ]
    )
    session.commit()

    history = snapshot_history(session)

    assert [at for at, _ in history] == [jan, feb, march]
    assert [{h.ticker for h in holdings} for _, holdings in history] == [
        {"NVDA"},
        {"NVDA", "VTI"},
        {"AAPL", "VTI"},
    ]


def test_snapshot_history_records_an_empty_account_update(session):
    account = _account(session)
    at = datetime(2024, 1, 1)
    session.add(AccountSnapshotRow(account_id=account.id, snapshot_at=at))
    session.commit()

    assert snapshot_history(session) == [(at, [])]


# ---- net_worth_series ------------------------------------------------------

def test_net_worth_series_is_empty_without_snapshots():
    assert net_worth_series([], FixedPriceMarket({})) == []


def test_net_worth_series_values_each_snapshot_at_that_snapshots_prices():
    jan = datetime(2024, 1, 1, 12, 0, 0)
    feb = datetime(2024, 2, 1, 12, 0, 0)
    market = FixedPriceMarket(
        {
            ("NVDA", jan.date()): 100.0,
            ("AAPL", jan.date()): 200.0,
            ("NVDA", feb.date()): 150.0,
            ("AAPL", feb.date()): 190.0,
        }
    )
    history = [
        (
            jan,
            [
                Holding(ticker="NVDA", shares=10, account_type=AccountType.brokerage),
                Holding(ticker="AAPL", shares=5, account_type=AccountType.roth),
            ],
        ),
        (
            feb,
            [
                Holding(ticker="NVDA", shares=12, account_type=AccountType.brokerage),
                Holding(ticker="AAPL", shares=5, account_type=AccountType.roth),
            ],
        ),
    ]

    points = net_worth_series(history, market)

    # 10*100 + 5*200 = 2000; then 12*150 + 5*190 = 2750.
    assert [p.net_worth for p in points] == [2000.0, 2750.0]
    assert [p.snapshot_at for p in points] == [jan, feb]
    assert [p.num_holdings for p in points] == [2, 2]


def test_net_worth_series_moves_on_price_alone_when_holdings_are_unchanged():
    """The whole point of price-on-date: a flat portfolio still has a curve."""
    jan = datetime(2024, 1, 1, 12, 0, 0)
    feb = datetime(2024, 2, 1, 12, 0, 0)
    holdings = [Holding(ticker="NVDA", shares=10, account_type=AccountType.brokerage)]
    market = FixedPriceMarket(
        {("NVDA", jan.date()): 100.0, ("NVDA", feb.date()): 130.0}
    )

    points = net_worth_series([(jan, holdings), (feb, holdings)], market)

    assert [p.net_worth for p in points] == [1000.0, 1300.0]


def test_net_worth_series_keeps_a_single_snapshot_as_one_point():
    at = datetime(2024, 1, 1, 12, 0, 0)
    market = FixedPriceMarket({("NVDA", at.date()): 100.0})
    points = net_worth_series(
        [(at, [Holding(ticker="NVDA", shares=10, account_type=AccountType.brokerage)])],
        market,
    )
    assert len(points) == 1
    assert points[0].net_worth == 1000.0


def test_net_worth_series_treats_an_unpriced_ticker_as_zero_not_a_crash():
    at = datetime(2024, 1, 1, 12, 0, 0)
    market = FixedPriceMarket({("NVDA", at.date()): 100.0})
    points = net_worth_series(
        [
            (
                at,
                [
                    Holding(ticker="NVDA", shares=10, account_type=AccountType.brokerage),
                    Holding(ticker="MYSTERY", shares=99, account_type=AccountType.brokerage),
                ],
            )
        ],
        market,
    )
    assert points[0].net_worth == 1000.0
    assert points[0].num_holdings == 2
