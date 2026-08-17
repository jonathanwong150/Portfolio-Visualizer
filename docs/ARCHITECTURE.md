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
| `BrokerAdapter`       | `MockBroker`          | `PlaidBroker` (Investments API)   |
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

## Data Model (PostgreSQL)

```
users
  └── accounts (type: brokerage | roth | 401k)
        └── holdings (security_id, shares, cost_basis, snapshot_at)

securities (ticker, name, type: stock|etf, sector, geography,
            market_cap, beta)
etf_constituents (etf_ticker, holding_ticker, weight)
price_history (ticker, date, close)
```

The prototype seeds `securities` + `etf_constituents` and can run entirely from
the seed dataset + a SQLite/Postgres store; Phase 3 adds live Plaid sync.

## API Surface

| Method | Path                        | Purpose                              |
|--------|-----------------------------|--------------------------------------|
| POST   | `/auth/login`               | JWT auth (single-user prototype)     |
| POST   | `/plaid/link`               | Create Plaid link token (Phase 3)    |
| POST   | `/plaid/sync`               | Sync holdings from broker            |
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
- **Accounts** — connect via Plaid, list synced accounts.

## Roadmap

- **Phase 0** — scaffold: repo structure, Docker Compose, FastAPI + React shells, seed loader.
- **Phase 1** — MVP: MockBroker → look-through → company exposure + sectors + beta; Dashboard + Exposure UI.
- **Phase 2** — overlap, factors, full risk suite, correlation, all visualizations.
- **Phase 3** — live Plaid sync, multi-account aggregation, snapshots.
- **Phase 4** — paid data upgrades, historical net-worth, export/share.
- **Phase 5** — React Native app reusing the backend.

## Risks

- **ETF look-through data** is the make-or-break dependency → isolated behind
  `ETFHoldingsProvider` with a seed fallback.
- **Plaid approval + cost** can gate live sync → mitigated by `MockBroker` + Sandbox-first.
- **Factor analysis** is approximate in the prototype → clearly upgradeable.
