"""Brokerage CSV import.

Pure ``str -> ParsedImport``: no DB, no HTTP, so the whole thing is unit-testable
against fixture files. Persisting a reviewed preview is ``services.snapshot``.

Two shapes of export exist, and they need different handling:

* **Positions** (Fidelity, Schwab, and our own template) — one row per holding.
* **Transactions** (Robinhood, which has no positions export) — one row per
  trade, aggregated into positions here.

Columns are located by *name*, never by index, so an extra or reordered column in
a future export doesn't silently shift every value one place to the left.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from app.models import (
    AccountType,
    ImportFormat,
    ParsedAccount,
    ParsedHolding,
    ParsedImport,
    SecurityType,
    SkippedRow,
)


class UnknownFormat(ValueError):
    """Raised when no header row matches a supported layout."""


# Ordered by preference: the first alias that matches a header cell exactly wins.
# Exact matching is what keeps "Cost Basis Total" from colliding with
# "Average Cost Basis".
_ALIASES: dict[str, tuple[str, ...]] = {
    "ticker": ("symbol", "ticker", "instrument"),
    "name": ("description", "security description", "name"),
    "shares": ("quantity", "shares", "qty", "quantity owned"),
    "price": ("last price", "price", "share price", "current price"),
    "value": ("current value", "market value", "total value", "value"),
    "cost_basis": ("cost basis total", "cost basis", "total cost", "cost"),
    "account": ("account name", "account", "account number"),
    "trans_code": ("trans code", "transaction code", "action"),
    "date": ("activity date", "run date", "date", "trade date"),
    "amount": ("amount", "net amount"),
}

# Sweep-account and money-market tickers. Real money, but no sector or
# constituents, so they're typed as cash rather than guessed at as equities.
_CASH_TICKERS = frozenset(
    {
        "SPAXX", "FDRXX", "FZFXX", "FCASH", "FMPXX",
        "SWVXX", "SNVXX", "SNSXX", "SCHO",
        "VMFXX", "VMRXX", "VUSXX",
    }
)

# Heuristic, not exhaustive — anything missed lands in `skipped` where it's
# visible, rather than being imported as an equity.
_CRYPTO_TICKERS = frozenset(
    {"BTC", "ETH", "DOGE", "SOL", "LTC", "BCH", "ETC", "XRP", "ADA", "AVAX", "SHIB", "MATIC"}
)

# Robinhood option trans codes: buy/sell to open/close.
_OPTION_CODES = frozenset({"BTO", "STC", "STO", "BTC"})
_OPTION_PATTERN = re.compile(r"\b(call|put)\b", re.IGNORECASE)

_BUY_CODES = frozenset({"BUY"})
_SELL_CODES = frozenset({"SELL"})

_SUMMARY_TICKERS = frozenset({"account total", "total", "cash & cash investments"})

_SCHWAB_TITLE = re.compile(r"positions for account\s+(.*?)(?:\s+\.\.\.|\s+as of|$)", re.IGNORECASE)

_MONEY_STRIP = re.compile(r"[$,+\s]")
_BLANKS = frozenset({"", "-", "--", "n/a", "na", "none"})


def _num(raw: str | None) -> float | None:
    """Parse brokerage money/quantity text. ``($4,200.00)`` is negative."""
    if raw is None:
        return None
    text = raw.strip().strip('"')
    if text.lower() in _BLANKS:
        return None

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = _MONEY_STRIP.sub("", text)
    if text.startswith("-"):
        negative = True
        text = text[1:]
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def _normalize(cell: str) -> str:
    return cell.strip().strip('"').strip().lower()


def _map_columns(header: list[str]) -> dict[str, int]:
    """Locate each canonical field in a header row, by exact alias match."""
    normalized = [_normalize(c) for c in header]
    mapping: dict[str, int] = {}
    for field, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[field] = normalized.index(alias)
                break
    return mapping


def _classify(columns: dict[str, int], normalized: list[str]) -> ImportFormat | None:
    if "trans_code" in columns and "ticker" in columns:
        return ImportFormat.robinhood_activity
    if "ticker" not in columns or "shares" not in columns:
        return None
    if "ticker" in columns and "account" in columns and "last price" in normalized:
        return ImportFormat.fidelity
    if "security type" in normalized or "market value" in normalized:
        return ImportFormat.schwab
    return ImportFormat.canonical


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def _find_header(rows: list[list[str]]) -> tuple[ImportFormat, int, dict[str, int]]:
    """Locate the header row. Real exports bury it under title/blank lines."""
    for index, row in enumerate(rows[:15]):
        if len(row) < 2:
            continue
        columns = _map_columns(row)
        fmt = _classify(columns, [_normalize(c) for c in row])
        if fmt is not None:
            return fmt, index, columns
    raise UnknownFormat(
        "Could not find a recognisable header row. Expected a column named one of "
        "'Symbol', 'Ticker' or 'Instrument' plus a quantity column — or use the "
        "template from /import/template.csv."
    )


def detect_format(text: str) -> ImportFormat:
    """The layout of an upload, or raise ``UnknownFormat``."""
    return _find_header(_rows(text))[0]


def infer_account_type(name: str) -> AccountType:
    """Guess an account type from its name. Always presented for confirmation.

    Deliberately narrow: "Traditional IRA" is not a Roth, so matching on "IRA"
    alone would be wrong.
    """
    lowered = name.lower()
    if "roth" in lowered:
        return AccountType.roth
    if "401" in lowered:
        return AccountType._401k
    return AccountType.brokerage


def _cell(row: list[str], columns: dict[str, int], field: str) -> str | None:
    index = columns.get(field)
    if index is None or index >= len(row):
        return None
    return row[index].strip()


def _security_type(ticker: str) -> SecurityType:
    # ETF-ness is decided later by the ETFHoldingsProvider, which actually knows.
    return SecurityType.cash if ticker.upper() in _CASH_TICKERS else SecurityType.stock


def _collect_accounts(holdings: list[ParsedHolding]) -> list[ParsedAccount]:
    """One entry per distinct account name, in first-seen order."""
    seen: dict[str, ParsedAccount] = {}
    for holding in holdings:
        if holding.account_name not in seen:
            seen[holding.account_name] = ParsedAccount(
                name=holding.account_name,
                account_type=infer_account_type(holding.account_name),
                inferred=True,
            )
    return list(seen.values())


def _parse_positions(
    rows: list[list[str]],
    header_index: int,
    columns: dict[str, int],
    fmt: ImportFormat,
    default_account: str,
) -> ParsedImport:
    holdings: list[ParsedHolding] = []
    skipped: list[SkippedRow] = []

    for offset, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(cell.strip() for cell in row):
            continue
        raw = ",".join(row).strip()
        # Footer disclaimers are single-column rows.
        if len(row) < 2:
            skipped.append(SkippedRow(line=offset, raw=raw, reason="Not a position row."))
            continue

        ticker = (_cell(row, columns, "ticker") or "").strip().strip('"')
        if not ticker:
            skipped.append(SkippedRow(line=offset, raw=raw, reason="No ticker in this row."))
            continue
        if ticker.lower() in _SUMMARY_TICKERS:
            skipped.append(SkippedRow(line=offset, raw=raw, reason="Summary row, not a holding."))
            continue

        shares = _num(_cell(row, columns, "shares"))
        if shares is None:
            skipped.append(
                SkippedRow(line=offset, raw=raw, reason="Could not read shares for this row.")
            )
            continue

        account_name = _cell(row, columns, "account") or default_account
        holdings.append(
            ParsedHolding(
                ticker=ticker.upper(),
                name=(_cell(row, columns, "name") or None),
                shares=shares,
                account_name=account_name or default_account,
                security_type=_security_type(ticker),
                price=_num(_cell(row, columns, "price")),
                value=_num(_cell(row, columns, "value")),
                cost_basis=_num(_cell(row, columns, "cost_basis")),
            )
        )

    return ParsedImport(
        source_format=fmt,
        accounts=_collect_accounts(holdings),
        holdings=holdings,
        skipped=skipped,
    )


def _trade_date(text: str | None) -> datetime:
    """Parse an activity date, or sort unparseable rows to the front."""
    for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime((text or "").strip(), pattern)
        except ValueError:
            continue
    return datetime.min


def _parse_robinhood(
    rows: list[list[str]], header_index: int, columns: dict[str, int]
) -> ParsedImport:
    """Aggregate a transaction history into current positions.

    Trades must be applied oldest-first or the weighted-average cost basis is
    wrong; Robinhood exports newest-first, so reverse then stable-sort by date.
    """
    body = [row for row in rows[header_index + 1 :] if any(cell.strip() for cell in row)]
    numbered = list(enumerate(body, start=header_index + 2))
    numbered.reverse()
    numbered.sort(key=lambda pair: _trade_date(_cell(pair[1], columns, "date")))

    positions: dict[str, dict[str, float]] = {}
    names: dict[str, str] = {}
    skipped: list[SkippedRow] = []
    warnings: list[str] = []

    for line, row in numbered:
        raw = ",".join(row).strip()
        instrument = (_cell(row, columns, "ticker") or "").strip().strip('"')
        code = (_cell(row, columns, "trans_code") or "").strip().upper()
        description = _cell(row, columns, "name") or ""

        if not instrument:
            skipped.append(
                SkippedRow(line=line, raw=raw, reason=f"Cash movement, not a position ({code}).")
            )
            continue
        if code in _OPTION_CODES or _OPTION_PATTERN.search(instrument):
            skipped.append(
                SkippedRow(line=line, raw=raw, reason="Options are not supported.")
            )
            continue
        if instrument.upper() in _CRYPTO_TICKERS:
            skipped.append(SkippedRow(line=line, raw=raw, reason="Crypto is not supported."))
            continue
        if code == "SPL":
            warnings.append(
                f"{instrument}: a stock split appears in this history. Share counts derived "
                "from trades do not account for splits — verify this position by hand."
            )
            skipped.append(SkippedRow(line=line, raw=raw, reason="Stock split, cannot aggregate."))
            continue
        if code not in _BUY_CODES | _SELL_CODES:
            skipped.append(SkippedRow(line=line, raw=raw, reason=f"Not a trade ({code})."))
            continue

        quantity = _num(_cell(row, columns, "quantity")) or _num(_cell(row, columns, "shares"))
        if quantity is None:
            skipped.append(SkippedRow(line=line, raw=raw, reason="Could not read shares for this row."))
            continue

        ticker = instrument.upper()
        names.setdefault(ticker, description)
        position = positions.setdefault(ticker, {"shares": 0.0, "cost": 0.0})
        price = _num(_cell(row, columns, "price"))
        amount = _num(_cell(row, columns, "amount"))

        if code in _BUY_CODES:
            spent = abs(amount) if amount is not None else (price or 0.0) * quantity
            position["shares"] += quantity
            position["cost"] += spent
        else:
            # Relieve sold shares at the running average so the remaining cost
            # basis reflects what's still held.
            average = position["cost"] / position["shares"] if position["shares"] else 0.0
            position["shares"] -= quantity
            position["cost"] = max(0.0, position["cost"] - average * quantity)

    holdings: list[ParsedHolding] = []
    for ticker, position in positions.items():
        shares = round(position["shares"], 6)
        if shares <= 0:
            warnings.append(
                f"{ticker}: fully sold in this history (0 shares) — excluded from the import."
            )
            continue
        holdings.append(
            ParsedHolding(
                ticker=ticker,
                name=names.get(ticker) or None,
                shares=shares,
                account_name="Robinhood",
                security_type=_security_type(ticker),
                cost_basis=round(position["cost"], 2),
            )
        )

    return ParsedImport(
        source_format=ImportFormat.robinhood_activity,
        accounts=_collect_accounts(holdings),
        holdings=holdings,
        skipped=skipped,
        warnings=warnings,
    )


def _default_account_name(rows: list[list[str]], header_index: int, fmt: ImportFormat) -> str:
    """Schwab names the account in a title line above the header."""
    if fmt is ImportFormat.schwab:
        for row in rows[:header_index]:
            match = _SCHWAB_TITLE.search(",".join(row))
            if match and match.group(1).strip():
                return match.group(1).strip()
        return "Schwab Account"
    return "Brokerage"


def parse_csv(text: str) -> ParsedImport:
    """Parse an upload into a reviewable preview. Raises ``UnknownFormat``."""
    rows = _rows(text)
    fmt, header_index, columns = _find_header(rows)

    if fmt is ImportFormat.robinhood_activity:
        return _parse_robinhood(rows, header_index, columns)
    return _parse_positions(
        rows, header_index, columns, fmt, _default_account_name(rows, header_index, fmt)
    )
