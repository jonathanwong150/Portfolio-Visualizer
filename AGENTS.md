# AGENTS.md — Portfolio Visualizer

## 1. Overview

A web app that aggregates investment holdings across accounts (brokerage / Roth / 401k), performs **ETF look-through** to reveal true underlying company exposure, and computes sector, factor, and risk analytics. FastAPI backend, React/TypeScript frontend, SQLite.

The point of the app is the look-through: "how much of my portfolio is *actually* NVIDIA, counting every ETF that holds it plus direct shares." Everything else is built on that number.

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — read it rather than re-deriving the design from code. Phases 1–4 are complete; **phase 5 (real data: CSV import + Alpha Vantage) is in progress**.

> **Not financial advice.** The app is for visualization only. Never present output as a recommendation, and don't add features that read as advice — the README disclaims this and it's a product constraint, not boilerplate.

## 2. Package map

| Path | Responsibility |
|---|---|
| `backend/app/main.py` | All FastAPI routes. 21 endpoints — health, portfolio (summary + history), exposure, overlap, factors, risk, export, import, market-data, plaid, accounts. |
| `backend/app/models.py` | Pydantic response models. The API contract the frontend types mirror. |
| `backend/app/config.py` | Settings via pydantic-settings. `database_url` defaults to SQLite here. |
| `backend/app/deps.py` | FastAPI dependency wiring — how providers get injected into routes. |
| `backend/app/analytics/engine.py` | `PortfolioAnalytics` — the core. Look-through, exposure, sectors, geography, overlap, correlation, risk metrics. **The heart of the app.** |
| `backend/app/analytics/factors.py` | Factor scoring: style, size, momentum, quality, beta. Pure functions, all `-> float \| None`. |
| `backend/app/analytics/history.py` | `net_worth_series` — values each holdings snapshot at its own date's prices. Pure; the DB read lives in `db_broker.snapshot_history`. |
| `backend/app/providers/` | Pluggable data sources behind interfaces: `base.py` (the protocols), `factory.py` (selection), `mock_broker.py`, `db_broker.py`, `plaid_broker.py`, `seed.py` (curated ETF holdings). |
| `backend/app/services/sync.py` | Plaid → DB sync orchestration (phase 3). |
| `backend/app/services/export.py` | CSV serialization of holdings and look-through exposure. Pure `-> str`; uses the stdlib `csv` writer so names containing commas are escaped. |
| `backend/app/services/import_csv.py` | Brokerage CSV → `ParsedImport`. Pure `str -> ParsedImport`. Fidelity/Schwab positions, Robinhood transaction aggregation, canonical template. Columns located by **name**, never index. |
| `backend/app/services/snapshot.py` | `write_snapshot` — the one write path shared by CSV import and Plaid sync. Accounts upserted on `plaid_account_id` or name; holdings and per-account snapshot markers appended, including empty updates. |
| `backend/app/providers/snapshot_broker.py` | `SnapshotBroker` — latest snapshot per account, `MockBroker` fallback only before any snapshot exists. **The default broker.** `PlaidBroker` subclasses it. |
| `backend/app/providers/snapshot_market.py` | Prices recorded by the import beat anything synthesized; metadata and history delegate to the seed. |
| `backend/app/providers/alphavantage.py` | AV client. Pure `map_*` functions carry the logic; `fetch_*` is HTTP only. |
| `backend/app/providers/cached_market.py` | `CachedMarketDataProvider` / `CachedETFHoldingsProvider` — read the cache, fall back to seed, **never HTTP**. |
| `backend/app/services/market_cache.py` | The three cache tables + staleness policy. Raw `OVERVIEW` stored verbatim so a mapping change is a re-map, not a re-fetch. |
| `backend/app/services/market_refresh.py` | The only thing that fetches. Prioritises prices → constituents → metadata, paces 1.5s, stops at a call budget. |
| `frontend/src/screens/Import.tsx` | Upload → preview → confirm account types → commit. |
| `backend/app/plaid_mapping.py` | Plaid security payloads → internal `Security` model. The messiest boundary; most Plaid bugs live here. |
| `backend/app/db/` | `session.py` (engine), `tables.py` (SQLAlchemy schema). |
| `frontend/src/screens/` | One file per screen: `Dashboard`, `Exposure`, `Overlap`, `Factors`, `Risk`, `Accounts`, `Import`. |
| `frontend/src/components/` | Shared UI — only `Card.tsx` and `Heatmap.tsx` so far. |
| `frontend/src/api.ts` | Every backend call. Change this when the API contract changes. |
| `backend/tests/` | pytest, one file per module, fixtures in `conftest.py`, sample broker exports and real Alpha Vantage payloads in `tests/fixtures/`. |

**Provider interfaces are the main design decision** — `BrokerAdapter`, `MarketDataProvider`, `ETFHoldingsProvider`. Data sources are swappable so the analytics engine never knows where holdings came from. Don't call Plaid or yfinance from the engine; go through a provider.

## 3. Critical code paths

**1. Holdings → true company exposure** (the core feature)
`GET /exposure/companies` → `main.py` → `deps.py` injects a `BrokerAdapter` → positions valued via `MarketDataProvider` → for each ETF position, `ETFHoldingsProvider` (`seed.py`) expands it into `ExposureLeaf` rows → `engine.py` aggregates leaves by company across all accounts → `BreakdownSlice` list.
The subtle part: the same company arrives from several ETFs *and* possibly a direct holding, and all of it must sum into one row.

**2. Plaid sync** (phase 3, in flight)
`POST /plaid/link` → link token → `POST /plaid/exchange` stores the access token → `POST /plaid/sync` → `services/sync.py` pulls holdings → `plaid_mapping.py` converts Plaid securities to internal `Security` objects → written via `db/tables.py` → subsequent reads use `db_broker.py` instead of `mock_broker.py`.
See `docs/ARCHITECTURE.md` §"Plaid sync data flow".

**3. Risk metrics**
`GET /risk/metrics` and `/risk/correlation` → `engine.py` → price history from `MarketDataProvider` → pandas/numpy for volatility, Sharpe, max drawdown, beta, correlation matrix.

## 4. Build & test

```bash
# Everything (from repo root)
docker-compose up --build          # api :8000, frontend :5173

# Backend
cd backend
./.venv/bin/pytest                 # full backend suite
./.venv/bin/pytest tests/test_engine.py -k lookthrough   # single test
./.venv/bin/uvicorn app.main:app --reload

# Frontend
cd frontend
npm test                           # vitest run
npm run test:watch                 # vitest in watch mode
npm run lint                       # eslint .
npm run build                      # tsc -b && vite build — type-check + build
npm run dev                        # vite dev server
```

**`npm run build` is not a test** — it proves the code compiles, nothing more. `npm test` is the test. Both must pass, plus `npm run lint`.

Test conventions: pytest in `backend/tests/`, one file per module, fixtures in `conftest.py`. Frontend tests are colocated as `*.test.ts`/`*.test.tsx` next to the code they cover.

## 5. Conventions & key decisions

Settled. Don't re-litigate without a reason:

- **Providers behind interfaces.** Every external data source (broker, market data, ETF holdings) sits behind a protocol in `providers/base.py`. This is what makes the app testable without network access — `mock_broker.py` and `seed.py` are why the suite runs offline in about a second.
- **SQLite now, Postgres later.** `config.py` defaults to `sqlite:///./portfolio.db`; `session.py` is written so `DATABASE_URL` can point at Postgres without touching call sites. The `db:` service in `docker-compose.yml` is **commented out** and intended for phase 3+.
- **Analytics are pure.** `engine.py` and `factors.py` take data and return numbers — no I/O, no DB, no HTTP. Keep it that way; it's why they're unit-testable.
- **Factor scores return `None`, not 0.** Missing data is not a neutral score. `_clamp` bounds real values; absent inputs propagate as `None` so the UI can distinguish "no data" from "average."
- **Pydantic models are the API contract.** `models.py` and `frontend/src/api.ts` must change together.

## 6. Test & lint harness

| | Backend | Frontend |
|---|---|---|
| Test runner | pytest 8.3.3 | Vitest 2.1 + React Testing Library, jsdom |
| Linter | – | ESLint 9 flat config (`eslint.config.js`) — `src/**/*.{ts,tsx}` plus root `*.js` config files |
| Setup | `tests/conftest.py` — in-memory SQLite fixtures | `src/setupTests.ts` — jest-dom matchers, RTL cleanup, `ResizeObserver` stub |

Two things about the frontend harness that will bite otherwise:

- **`ResizeObserver` is stubbed in `src/setupTests.ts` because jsdom lacks it** and recharts' `ResponsiveContainer` constructs one in a passive effect. Without the stub the throw tears down the React tree, and every assertion after a chart renders fails with a misleading "unable to find element". Don't remove it when touching a chart test.
- **Test files are type-checked by `npm run build`** — `tsconfig.json` has `include: ["src"]` with `noUnusedLocals`, so a sloppy test breaks the build, not just the suite.

Rendering a component is still not proof a number is right. Charts and analytics get the `~/Projects/AGENTS.md` treatment on top of the unit tests: exercise it in the browser, check empty/loading/error, and verify one number against an independently computed value.

## 7. Gotchas

- **README says "Database: PostgreSQL" — it isn't.** The app runs on SQLite (`backend/portfolio.db`); the Postgres compose service is commented out and the README's tech-stack table describes the phase-3 target, not today. Trust `config.py` over the README. (2026-08-25)
- **A moved `.venv` is broken, not stale** — `bin/activate` hardcodes an absolute `VIRTUAL_ENV`. After any directory move, `rm -rf .venv && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt`. The repo moved from `~/Downloads` on 2026-08-25 and this bit. (2026-08-25)
- **`npm run build` is a type-check, not a test.** `tsc -b && vite build` proves it compiles. It says nothing about whether a number on screen is correct. (2026-08-25)
- **Plaid: sandbox credentials only on this machine.** Never put production Plaid keys in `.env` locally. Tokens must never be logged — `plaid_mapping.py` and `services/sync.py` are where an accidental `print` would leak one.
- **`.env.example` must change in the same commit as a new setting**, or the next clone fails with a confusing pydantic-settings validation error rather than a missing-variable message.
- **A screen's tests suddenly fail with "unable to find element" after you add an export to `api.ts`** — `vi.mock("../api", () => ({...}))` replaces *every* export, so a newly-used one is `undefined` and the component throws before rendering. Use `vi.mock("../api", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api")>()), api: {...} }))` so only what you stub is stubbed. (2026-08-26)
- **Look-through overstates single-name exposure whenever constituent data is partial.** `engine.py` redistributes an ETF's uncovered weight across its *mapped* constituents, scaling each by `1 / covered_weight`. The seed covers 38.9% of SPY, so a 6.5% NVDA weight presents as ~16.7%. Totals still reconcile to net worth; the split between names does not. Don't quote a per-company percentage as fact until a provider returns full constituents. (2026-08-28)
- **Alpha Vantage's free tier is 25 requests/day, and a ~20-ticker portfolio wants ~40.** Confirmed from its own response body, not the docs. `market_refresh` therefore orders work prices → ETF constituents → metadata, so a truncated run still leaves the most useful partial state. Expect two days to warm up from cold. (2026-09-01)
- **Alpha Vantage signals three different things through HTTP 200, and conflating any two breaks a refresh.** `Note`/`Information` = rate limited (stop the run). `Error Message` = invalid symbol (skip that ticker). `{}` = no overview for a symbol it still *quotes* fine — true of many commodity/crypto trusts like GLD and IBIT, so never let an empty overview suppress the price fetch. (2026-09-01)
- **Alpha Vantage's sector vocabulary differs from the seed's**, not just in case: `CONSUMER CYCLICAL` vs `Consumer Discretionary`, `FINANCIAL SERVICES` vs `Financials`, `HEALTHCARE` vs `Health Care`. Unmapped, one sector shows as two rows in the same breakdown. `_SECTOR_ALIASES` in `alphavantage.py` is the fix; extend it when a new sector appears. (2026-09-01)
- **Every seed price is ~$100–108 regardless of ticker** — `SeedMarketDataProvider` random-walks from a base of 100, so a $1.00 money-market fund gets valued at $106/share and net worth comes out multiples too high. Imported snapshot prices override this (`snapshot_market.py`); a ticker with no imported price still gets a fabricated one. (2026-08-28)
- **Tests that hit a DB-backed provider must inject the session.** `get_broker`/`get_market_data` take an optional `session`; without it they open `SessionLocal` and read the developer's real `portfolio.db`, so overriding `get_db` alone does not isolate a test. `deps.get_analytics` threads the request session through — keep it that way. (2026-08-28)
- **Accounts disappear after separate imports if reads use a global snapshot timestamp.** Use `db_broker.current_holding_rows` and `latest_account_snapshot_times` for current-state consumers; include `account_snapshots` markers so empty updates clear holdings and never trigger demo fallback. Legacy holding timestamps remain valid events. (2026-09-08)
- **Yahoo Finance returns HTTP 429 from this network** on every endpoint, with or without a browser user-agent. Alpha Vantage and Twelve Data work. Don't conclude "no live market data available" from a Yahoo failure. (2026-08-28)
- **`backend/portfolio.db` is gitignored and local.** Schema changes have no migration tooling yet — deleting the file and letting it recreate is the current answer, which also destroys local data.
