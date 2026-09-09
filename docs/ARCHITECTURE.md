# Architecture

## Overview

Portfolio Visualizer is a responsive web app with a Python analytics backend and
a React frontend. The defining capability is the **ETF look-through engine**:
expanding every ETF into its underlying constituents so we can compute a user's
*true* exposure to each company, sector, factor, and geography — netted across
all accounts and funds.

```
┌───────────┐     ┌──────────────────────────────┐     ┌────────────┐
│  React /  │◀───▶│           FastAPI            │◀───▶│ PostgreSQL │
│    TS     │ REST│  ┌────────────────────────┐  │     └────────────┘
│ (Vite)    │     │  │   Analytics Engine     │  │
└───────────┘     │  │  look-through / risk   │  │     ┌────────────┐
                  │  └────────────────────────┘  │────▶│  Providers │
                  │  broker / market / etf       │     │ Plaid /    │
                  └──────────────────────────────┘     │ yfinance / │
                                                        │ seed ETFs  │
                                                        └────────────┘
```

## Provider Interfaces (dependency isolation)

Every external dependency sits behind an interface so the prototype runs on
free/mock data and can be upgraded without touching business logic.

| Interface             | Prototype impl            | Upgrade path                      |
|-----------------------|---------------------------|-----------------------------------|
| `BrokerAdapter`       | `MockBroker`              | `PlaidBroker` / `DbBroker` (Investments API) ✅ |
| `MarketDataProvider`  | Alpha Vantage → import price → seed ✅ | paid tier for higher request limits |
| `ETFHoldingsProvider` | Alpha Vantage `ETF_PROFILE` → seed ✅ | Morningstar for full constituents |

`SeedMarketDataProvider` synthesizes price history from each security's beta and
is now only the last fallback. Yahoo Finance is unusable here — it returns HTTP
429 from this network — which is why Alpha Vantage is the provider.

### Why ETF look-through is isolated
Free APIs don't reliably expose full ETF constituents. The prototype ships a
curated **seed dataset** (`backend/app/data/etf_seed.json`) of popular ETFs with
their top holdings + weights. This keeps the app fully functional while making
the one component most likely to need paid data a drop-in swap.

## Analytics Engine

Located in `backend/app/analytics/`.

1. **Look-through resolver** — expands each ETF position into
   `(underlying_ticker, weight × position_value)`, then nets duplicates across
   ETFs and direct holdings → **true per-company exposure**.
2. **Overlap analysis** — pairwise shared-weight between ETFs.
3. **Breakdowns** — sector / geography / market-cap / asset class (post look-through).
4. **Factor analysis** — growth vs value, size, momentum, quality (rule-based
   proxies in the prototype; Fama-French regression later).
5. **Risk metrics** — beta (vs SPY), annualized volatility, Sharpe, max drawdown;
   correlation matrix.
6. **Summary** — net worth, total invested, allocation by account & asset class.

## Data Model

Implemented in `backend/app/db/` — SQLAlchemy models (`tables.py`) on an engine
configured by `DATABASE_URL` (`session.py`). SQLite by default so the prototype
has no external dependencies; the same models run on Postgres unchanged.

```
users
  └── accounts (plaid_account_id, name, type: brokerage | roth | 401k, institution)
        ├── account_snapshots (account_id, snapshot_at)
        └── holdings (ticker, shares, cost_basis, price, snapshot_at)

securities (ticker, name, type: stock|etf)
plaid_items (access_token, item_id, institution)
```

`accounts.type` stores the `AccountType` **value** (`"401k"`, not the Python
member name `_401k`) and is reconstructed with `AccountType(row.type)`.

`etf_constituents`, `price_history` and `security_metadata` are real tables now,
populated from Alpha Vantage; `etf_seed.json` is the offline fallback.

### Holdings snapshots

Holdings are **append-only**. Each import or sync replaces the holdings of the
accounts it supplies, leaving other accounts at their last known holdings.
The current portfolio combines the latest snapshot **per account**, shared by
analytics, account summaries, exports, and market-data refresh/coverage.

Each supplied account also gets an `account_snapshots` record, even when it has
no holdings. An empty update clears that account without reviving an older
position or triggering demo fallback. Demo holdings are available only before
any snapshot has been recorded. A CSV commit still requires nonempty holdings;
Plaid can report an account with none.

Snapshot selection includes legacy timestamps from `holdings`, so existing data
works without backfill. Startup creates the additive `account_snapshots` table;
no existing tables or rows are replaced. Reverting to code that ignores these
records loses empty-account semantics and restores the global-snapshot bug.
Accounts are upserted by `plaid_account_id` for Plaid or by name for CSV imports;
cross-source account reconciliation remains a separate concern.

### CSV import (Phase 5)

```
Fidelity / Schwab positions  ─┐
Robinhood transaction history ─┼─▶ services/import_csv.parse_csv()  (pure)
Canonical template           ─┘        │ ParsedImport (+ skipped, warnings)
                                       ▼
                            POST /import/preview  ── review in the UI ──┐
                                                                        │
                            POST /import/commit ──▶ services/snapshot.write_snapshot()
                                                          │
                                    accounts (upsert) + holdings (new snapshot)
                                                          │
                                    SnapshotBroker ───────┘  (MockBroker fallback
                                                              before any snapshot)
```

`write_snapshot` is the single write path, shared with Plaid sync. Columns are
located by **name**, so a reordered or extra column in a future export can't
silently shift values. Options, crypto and cash movements are reported in
`skipped` with reasons rather than dropped.

Imported prices are authoritative: `HoldingRow.price` stores what the broker
reported, and `SnapshotMarketDataProvider` serves it in preference to anything
synthesized — each snapshot valued at its own recorded prices. Robinhood
transaction histories carry no current price, so those positions still fall back
to the seed until a real market-data provider lands.

### Market data (Phase 5)

```
POST /market-data/refresh ──▶ services/market_refresh   (the ONLY fetcher)
                                    │ prices → constituents → metadata
                                    ▼
                        providers/alphavantage  fetch_* / map_*
                                    │
                    security_metadata · etf_constituents · price_history
                                    │
   CachedMarketDataProvider ────────┘   SnapshotMarketDataProvider ──▶ Seed
        (fetched closes)                  (broker export price)     (synthesized)
```

Price precedence, best first: **fetched daily closes → the price the broker
export carried → the seed's synthesized series.** The import price is what covers
instruments Alpha Vantage can't quote, such as a 401(k) collective trust with no
ticker.

Reads never make a network call, mirroring the Plaid decision above. The free
tier allows **25 requests/day** against a ~20-ticker portfolio wanting ~40, so
`_plan` groups work by type — prices first, then ETF constituents, then
fundamentals — and a truncated run leaves the most useful partial state.

`GET /market-data/coverage` reports how much of the portfolio has real data, and
per-ETF constituent depth: a look-through percentage is only as trustworthy as
the fraction of the fund its constituent list covers.

### Net-worth history (Phase 4)

`GET /portfolio/history` reconstructs the complete portfolio at each recorded
account update (`db_broker.snapshot_history`), carrying unchanged accounts
forward and replacing or clearing updated accounts. It values each point at
the prices in effect **on its own date**, via
`MarketDataProvider.get_price_on`. Valuing every snapshot at today's prices
would flatten the market out and turn the series into a contributions chart, so
the curve moves on both market moves and holdings changes.

The interface default derives `get_price_on` from `get_price_history` by walking
back calendar days from the newest close, clamped at both ends. The seed series
is 252 *trading* days treated as consecutive calendar days — a deliberate
prototype simplification. `MarketDataProvider.prices_are_synthesized` surfaces
in the response as `prices_synthesized` so the UI captions generated prices
rather than presenting them as observed history.

### Plaid sync data flow

```
Plaid Link (frontend)
   │ public_token
   ▼
POST /plaid/exchange ──▶ exchange_public_token() ──▶ plaid_items row
                                                          │
POST /plaid/sync ──▶ services/sync.sync_holdings() ◀──────┘
                          │ fetch_investments(access_token)
                          ▼
                    accounts (upsert) + holdings (new snapshot) + securities (upsert)
                          │
        DbBroker ─────────┘  reads latest snapshot per account → list[Holding]
             ▲
        PlaidBroker  (falls back to MockBroker when unconfigured and unsynced)
             ▲
        Analytics Engine (unchanged — still just a BrokerAdapter)
```

`PlaidBroker` never calls Plaid on the read path, so analytics requests stay
fast and offline-safe. The `plaid` package is imported lazily inside each helper
in `providers/plaid_broker.py`, and every entry point guards on
`settings.plaid_configured` so missing credentials degrade instead of crashing.

## API Surface

All 21 routes live in `backend/app/main.py`. There is **no authentication** — the
app is a single-user local prototype; auth is a Phase 5 concern that arrives with
the mobile app.

| Method | Path                        | Purpose                              |
|--------|-----------------------------|--------------------------------------|
| GET    | `/health`                   | Liveness                             |
| POST   | `/plaid/link`               | Create Plaid Link token (`configured:false` when unset) |
| POST   | `/plaid/exchange`           | Exchange `public_token`, store Plaid Item |
| POST   | `/plaid/sync`               | Sync holdings from broker (409 if unconfigured) |
| GET    | `/accounts`                 | Synced accounts, valued at current prices |
| GET    | `/portfolio/summary`        | Net worth, invested, allocation      |
| GET    | `/portfolio/history`        | Net worth per snapshot, each at its own date's prices |
| GET    | `/exposure/companies`       | True company exposure (look-through) |
| GET    | `/exposure/sectors`         | Sector breakdown                     |
| GET    | `/exposure/factors`         | Factor tilts                         |
| GET    | `/exposure/geography`       | Geographic breakdown                 |
| GET    | `/overlap`                  | ETF overlap matrix                   |
| GET    | `/risk/metrics`             | Beta, volatility, Sharpe, drawdown   |
| GET    | `/risk/correlation`         | Correlation matrix                   |
| POST   | `/market-data/refresh`      | Fetch real prices/fundamentals/constituents |
| GET    | `/market-data/coverage`     | How much of the portfolio has real data |
| POST   | `/import/preview`           | Parse a brokerage CSV for review (writes nothing) |
| POST   | `/import/commit`            | Persist a reviewed preview as a snapshot |
| GET    | `/import/template.csv`      | Canonical import template            |
| GET    | `/export/holdings.csv`      | Raw positions as CSV (attachment)    |
| GET    | `/export/exposure.csv`      | Look-through exposure as CSV (attachment) |

## Frontend Screens

- **Dashboard** — net worth, total invested, allocation donut, top-10 true exposures.
- **Exposure** — treemap + searchable list ("you own X% NVIDIA across N funds").
- **Overlap** — ETF overlap heatmap.
- **Sectors / Factors** — toggleable bar/pie/treemap; factor tilt bars.
- **Risk** — beta/vol/Sharpe/drawdown cards + correlation heatmap.
- **Accounts** — connect via Plaid Link, sync holdings, list synced accounts with
  live values; shows a banner and disables the actions when Plaid isn't configured.

## Roadmap

- **Phase 0** ✅ — scaffold: repo structure, Docker Compose, FastAPI + React shells, seed loader.
- **Phase 1** ✅ — MVP: MockBroker → look-through → company exposure + sectors + beta; Dashboard + Exposure UI.
- **Phase 2** ✅ — overlap, factors, full risk suite, correlation, all visualizations.
- **Phase 3** ✅ — live Plaid sync, multi-account aggregation, snapshots, SQLite persistence, Accounts screen.
- **Phase 4** *(in progress)* — historical net-worth ✅, CSV export ✅; paid data
  upgrades and share links outstanding.
- **Phase 5** *(in progress)* — usable with real data: CSV import ✅ (Fidelity,
  Schwab, Robinhood), DB-backed broker by default ✅; live market data via
  Alpha Vantage ✅ (prices, fundamentals, ETF constituents, cached in SQLite).
- **Phase 5** — React Native app reusing the backend; authentication arrives with it.

## Risks

- **ETF look-through data** is the make-or-break dependency → isolated behind
  `ETFHoldingsProvider` with a seed fallback.
- **Plaid approval + cost** can gate live sync → mitigated by `MockBroker` + Sandbox-first.
- **Factor analysis** is approximate in the prototype → clearly upgradeable.

## Completed Work

- 2026-09-08: Preserve independently imported and synced accounts across portfolio
  views and history. Record empty account snapshots, retain compatibility with
  legacy holdings, and reject CSV commits with unmatched account references.
