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

| Interface             | Prototype impl        | Upgrade path                      |
|-----------------------|-----------------------|-----------------------------------|
| `BrokerAdapter`       | `MockBroker`          | `PlaidBroker` / `DbBroker` (Investments API) ✅ |
| `MarketDataProvider`  | `YFinanceProvider`    | Financial Modeling Prep / EOD     |
| `ETFHoldingsProvider` | `SeedETFProvider`     | FMP `etf-holdings` / Morningstar  |

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
        └── holdings (ticker, shares, cost_basis, snapshot_at)

securities (ticker, name, type: stock|etf)
plaid_items (access_token, item_id, institution)
```

`accounts.type` stores the `AccountType` **value** (`"401k"`, not the Python
member name `_401k`) and is reconstructed with `AccountType(row.type)`.

`etf_constituents` and `price_history` remain seed-file backed
(`backend/app/data/etf_seed.json`) until the paid-data upgrade in Phase 4.

### Holdings snapshots

Holdings are **append-only**. Every sync writes a fresh set of rows sharing one
`snapshot_at`, so history is preserved and "the current portfolio" is simply all
rows at `max(snapshot_at)`. Accounts, by contrast, are upserted in place on
`plaid_account_id`.

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
        DbBroker ─────────┘  reads max(snapshot_at) → list[Holding]
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

| Method | Path                        | Purpose                              |
|--------|-----------------------------|--------------------------------------|
| POST   | `/auth/login`               | JWT auth (single-user prototype)     |
| POST   | `/plaid/link`               | Create Plaid Link token (`configured:false` when unset) |
| POST   | `/plaid/exchange`           | Exchange `public_token`, store Plaid Item |
| POST   | `/plaid/sync`               | Sync holdings from broker (409 if unconfigured) |
| GET    | `/accounts`                 | Synced accounts, valued at current prices |
| GET    | `/portfolio/summary`        | Net worth, invested, allocation      |
| GET    | `/exposure/companies`       | True company exposure (look-through) |
| GET    | `/exposure/sectors`         | Sector breakdown                     |
| GET    | `/exposure/factors`         | Factor tilts                         |
| GET    | `/exposure/geography`       | Geographic breakdown                 |
| GET    | `/overlap`                  | ETF overlap matrix                   |
| GET    | `/risk/metrics`             | Beta, volatility, Sharpe, drawdown   |
| GET    | `/risk/correlation`         | Correlation matrix                   |

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
- **Phase 4** — paid data upgrades, historical net-worth, export/share.
- **Phase 5** — React Native app reusing the backend.

## Risks

- **ETF look-through data** is the make-or-break dependency → isolated behind
  `ETFHoldingsProvider` with a seed fallback.
- **Plaid approval + cost** can gate live sync → mitigated by `MockBroker` + Sandbox-first.
- **Factor analysis** is approximate in the prototype → clearly upgradeable.
