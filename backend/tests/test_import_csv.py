"""Tests for brokerage CSV import.

Parsers are the textbook input->output contract, so these are written against
fixture files shaped like the real exports — preamble lines, footer disclaimers,
``$1,234.56`` money, quoted descriptions containing commas, and summary rows.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models import AccountType, SecurityType
from app.services.import_csv import (
    ImportFormat,
    UnknownFormat,
    detect_format,
    infer_account_type,
    parse_csv,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture
def fidelity() -> str:
    return _read("fidelity_positions.csv")


@pytest.fixture
def schwab() -> str:
    return _read("schwab_positions.csv")


@pytest.fixture
def robinhood() -> str:
    return _read("robinhood_activity.csv")


# ---- format detection -------------------------------------------------------

def test_detects_each_supported_format(fidelity, schwab, robinhood):
    assert detect_format(fidelity) is ImportFormat.fidelity
    assert detect_format(schwab) is ImportFormat.schwab
    assert detect_format(robinhood) is ImportFormat.robinhood_activity


def test_detects_the_canonical_template():
    text = "ticker,shares,account,cost_basis\nNVDA,10,brokerage,1500\n"
    assert detect_format(text) is ImportFormat.canonical


def test_unrecognised_header_raises_a_usable_message():
    with pytest.raises(UnknownFormat) as exc:
        detect_format("alpha,beta,gamma\n1,2,3\n")
    # The message must name what it looked for, not just fail.
    assert "ticker" in str(exc.value).lower()


def test_an_empty_file_is_rejected_not_silently_empty():
    with pytest.raises(UnknownFormat):
        detect_format("")


# ---- account type inference -------------------------------------------------

@pytest.mark.parametrize(
    "name,expected",
    [
        ("ROTH IRA", AccountType.roth),
        ("Roth Contributory IRA", AccountType.roth),
        ("401(K) PLAN", AccountType._401k),
        ("My 401k", AccountType._401k),
        ("Individual", AccountType.brokerage),
        ("Joint WROS", AccountType.brokerage),
        ("", AccountType.brokerage),
        # "Traditional IRA" is not a Roth — must not match on "IRA" alone.
        ("Traditional IRA", AccountType.brokerage),
    ],
)
def test_infer_account_type(name, expected):
    assert infer_account_type(name) is expected


# ---- Fidelity ---------------------------------------------------------------

def test_fidelity_parses_positions_and_skips_preamble_and_footer(fidelity):
    result = parse_csv(fidelity)

    assert result.source_format is ImportFormat.fidelity
    by_ticker = {h.ticker: h for h in result.holdings}
    assert set(by_ticker) == {"NVDA", "SPY", "VTI", "BRK.B", "SPAXX"}

    nvda = by_ticker["NVDA"]
    assert nvda.shares == 40.0
    assert nvda.price == 182.50
    assert nvda.cost_basis == 6000.00
    assert nvda.account_name == "Individual"


def test_fidelity_strips_currency_symbols_and_thousands_separators(fidelity):
    spy = next(h for h in parse_csv(fidelity).holdings if h.ticker == "SPY")
    assert spy.price == 641.20
    assert spy.value == 19236.00
    assert spy.cost_basis == 15000.00


def test_fidelity_keeps_a_quoted_description_containing_a_comma_intact(fidelity):
    brk = next(h for h in parse_csv(fidelity).holdings if h.ticker == "BRK.B")
    assert brk.name == "BERKSHIRE HATHAWAY INC, CLASS B"
    assert brk.shares == 5.0


def test_fidelity_finds_both_accounts_and_infers_their_types(fidelity):
    accounts = {a.name: a for a in parse_csv(fidelity).accounts}
    assert set(accounts) == {"Individual", "ROTH IRA"}
    assert accounts["Individual"].account_type is AccountType.brokerage
    assert accounts["ROTH IRA"].account_type is AccountType.roth
    # Every inferred type is flagged so the UI can ask for confirmation.
    assert all(a.inferred for a in accounts.values())


def test_a_money_market_fund_is_classified_as_cash(fidelity):
    spaxx = next(h for h in parse_csv(fidelity).holdings if h.ticker == "SPAXX")
    assert spaxx.security_type is SecurityType.cash
    # Still counts toward the portfolio — it is real money.
    assert spaxx.value == 1502.34


def test_an_ordinary_ticker_claims_no_type_so_etf_detection_still_runs(fidelity):
    """Guessing "stock" here would overwrite the ETF provider's answer."""
    holdings = {h.ticker: h for h in parse_csv(fidelity).holdings}
    assert holdings["SPY"].security_type is None
    assert holdings["NVDA"].security_type is None


# ---- Schwab -----------------------------------------------------------------

def test_schwab_parses_positions(schwab):
    result = parse_csv(schwab)

    by_ticker = {h.ticker: h for h in result.holdings}
    assert set(by_ticker) == {"AAPL", "QQQ", "SCHD"}
    assert by_ticker["AAPL"].shares == 50.0
    assert by_ticker["AAPL"].price == 228.40
    assert by_ticker["QQQ"].value == 14952.50
    assert by_ticker["SCHD"].cost_basis == 5000.00


def test_schwab_drops_the_cash_and_total_summary_rows(schwab):
    result = parse_csv(schwab)
    tickers = {h.ticker for h in result.holdings}
    assert "Account Total" not in tickers
    assert "Cash & Cash Investments" not in tickers
    # Dropped rows are reported, never silent.
    assert any("Account Total" in s.raw for s in result.skipped)


def test_schwab_takes_the_account_name_from_its_title_line(schwab):
    accounts = parse_csv(schwab).accounts
    assert len(accounts) == 1
    assert "Roth" in accounts[0].name
    assert accounts[0].account_type is AccountType.roth


def test_schwab_quoted_description_with_a_comma_survives(schwab):
    qqq = next(h for h in parse_csv(schwab).holdings if h.ticker == "QQQ")
    assert qqq.name == "INVESCO QQQ TRUST, SERIES 1"


# ---- Robinhood transaction aggregation --------------------------------------

def test_robinhood_nets_buys_and_sells_into_a_position(robinhood):
    by_ticker = {h.ticker: h for h in parse_csv(robinhood).holdings}

    # 10 @ $420 + 5 @ $440 = 15 shares for $6,400; sell 3 leaves 12.
    msft = by_ticker["MSFT"]
    assert msft.shares == 12.0
    # Weighted average cost is 6400/15 = 426.666..., so 12 shares cost $5,120.
    assert msft.cost_basis == pytest.approx(5120.0)


def test_robinhood_keeps_a_single_buy_intact(robinhood):
    tsla = next(h for h in parse_csv(robinhood).holdings if h.ticker == "TSLA")
    assert tsla.shares == 20.0
    assert tsla.cost_basis == pytest.approx(5000.0)


def test_robinhood_excludes_a_fully_sold_position(robinhood):
    result = parse_csv(robinhood)
    # Bought 2.5 and sold 2.5 — a zero position is not a holding.
    assert "AMZN" not in {h.ticker for h in result.holdings}
    assert any("AMZN" in w for w in result.warnings)


def test_robinhood_skips_options_crypto_and_cash_movements(robinhood):
    result = parse_csv(robinhood)
    reasons = {s.raw: s.reason for s in result.skipped}

    option = next(r for r in reasons if "Call $180.00" in r)
    assert "option" in reasons[option].lower()

    crypto = next(r for r in reasons if "Bitcoin" in r)
    assert "crypto" in reasons[crypto].lower()

    deposit = next(r for r in reasons if "ACH Deposit" in r)
    assert reasons[deposit]

    # None of them became holdings.
    assert {"BTC", "NVDA"}.isdisjoint({h.ticker for h in result.holdings})


def test_robinhood_skips_a_dividend_without_treating_it_as_shares(robinhood):
    tsla = next(h for h in parse_csv(robinhood).holdings if h.ticker == "TSLA")
    # The CDIV row must not add to the share count.
    assert tsla.shares == 20.0


def test_robinhood_warns_loudly_about_a_stock_split(robinhood):
    result = parse_csv(robinhood)
    # A split makes the derived share count untrustworthy — it must be shouted
    # about, not quietly folded in.
    assert any("GOOGL" in w and "split" in w.lower() for w in result.warnings)


def test_robinhood_reports_its_source_format(robinhood):
    assert parse_csv(robinhood).source_format is ImportFormat.robinhood_activity


def test_robinhood_applies_trades_in_date_order_not_file_order():
    """Cost basis depends on *when* each trade happened, not row position.

    Rows here are deliberately neither ascending nor descending by date, so
    merely reversing the file gives the wrong weighted average.
    """
    text = (
        '"Activity Date","Instrument","Description","Trans Code","Quantity","Price","Amount"\n'
        '"8/20/2026","KO","Coca-Cola Co","Buy","5","$500.00","($2,500.00)"\n'
        '"8/26/2026","KO","Coca-Cola Co","Sell","3","$450.00","$1,350.00"\n'
        '"8/18/2026","KO","Coca-Cola Co","Buy","10","$400.00","($4,000.00)"\n'
    )

    ko = next(h for h in parse_csv(text).holdings if h.ticker == "KO")

    # Chronological: buy 10 @400 then 5 @500 => 15 shares / $6,500, avg $433.33.
    # Selling 3 relieves $1,300, leaving 12 shares at $5,200.
    # Reversing the file instead would apply the sell too early and yield $5,300.
    assert ko.shares == 12.0
    assert ko.cost_basis == pytest.approx(5200.0)


# ---- canonical template -----------------------------------------------------

def test_canonical_template_round_trips():
    text = (
        "ticker,shares,account,cost_basis\n"
        "NVDA,10,brokerage,1500\n"
        "VOO,5.5,Roth IRA,2000\n"
    )
    result = parse_csv(text)

    by_ticker = {h.ticker: h for h in result.holdings}
    assert by_ticker["NVDA"].shares == 10.0
    assert by_ticker["VOO"].shares == 5.5
    assert by_ticker["VOO"].account_name == "Roth IRA"
    accounts = {a.name: a.account_type for a in result.accounts}
    assert accounts["Roth IRA"] is AccountType.roth


def test_canonical_tolerates_a_missing_cost_basis():
    result = parse_csv("ticker,shares,account\nNVDA,10,brokerage\n")
    assert result.holdings[0].cost_basis is None


def test_a_row_with_no_ticker_is_skipped_with_a_reason():
    result = parse_csv("ticker,shares,account\n,10,brokerage\nNVDA,5,brokerage\n")
    assert [h.ticker for h in result.holdings] == ["NVDA"]
    assert len(result.skipped) == 1


def test_a_row_with_unparseable_shares_is_skipped_not_zeroed():
    result = parse_csv("ticker,shares,account\nNVDA,n/a,brokerage\n")
    assert result.holdings == []
    assert "shares" in result.skipped[0].reason.lower()
