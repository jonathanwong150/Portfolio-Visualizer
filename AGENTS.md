# AGENTS.md — Portfolio Visualizer

## 1. Overview

A web app that aggregates investment holdings across accounts (brokerage / Roth / 401k), performs **ETF look-through** to reveal true underlying company exposure, and computes sector, factor, and risk analytics. FastAPI backend, React/TypeScript frontend, SQLite.

The point of the app is the look-through: "how much of my portfolio is *actually* NVIDIA, counting every ETF that holds it plus direct shares." Everything else is built on that number.

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — read it rather than re-deriving the design from code. Phases 1–3 are complete (phase 3 = live Plaid sync); **phase 4 (paid data, historical net worth, export) is in progress**.

> **Not financial advice.** The app is for visualization only. Never present output as a recommendation, and don't add features that read as advice — the README disclaims this and it's a product constraint, not boilerplate.

## 2. Package map

| Path | Responsibility |
|---|---|
| `backend/app/main.py` | All FastAPI routes. 13 endpoints — health, portfolio, exposure, overlap, factors, risk, plaid, accounts. |
| `backend/app/models.py` | Pydantic response models. The API contract the frontend types mirror. |
| `backend/app/config.py` | Settings via pydantic-settings. `database_url` defaults to SQLite here. |
| `backend/app/deps.py` | FastAPI dependency wiring — how providers get injected into routes. |
| `backend/app/analytics/engine.py` | `PortfolioAnalytics` — the core. Look-through, exposure, sectors, geography, overlap, correlation, risk metrics. **The heart of the app.** |
| `backend/app/analytics/factors.py` | Factor scoring: style, size, momentum, quality, beta. Pure functions, all `-> float \| None`. |
| `backend/app/providers/` | Pluggable data sources behind interfaces: `base.py` (the protocols), `factory.py` (selection), `mock_broker.py`, `db_broker.py`, `plaid_broker.py`, `seed.py` (curated ETF holdings). |
| `backend/app/services/sync.py` | Plaid → DB sync orchestration (phase 3). |
| `backend/app/plaid_mapping.py` | Plaid security payloads → internal `Security` model. The messiest boundary; most Plaid bugs live here. |
| `backend/app/db/` | `session.py` (engine), `tables.py` (SQLAlchemy schema). |
| `frontend/src/screens/` | One file per screen: `Dashboard`, `Exposure`, `Overlap`, `Factors`, `Risk`, `Accounts`. |
| `frontend/src/components/` | Shared UI — only `Card.tsx` and `Heatmap.tsx` so far. |
| `frontend/src/api.ts` | Every backend call. Change this when the API contract changes. |
| `backend/tests/` | pytest, one file per module, fixtures in `conftest.py`. 47 tests. |

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
./.venv/bin/pytest                 # 47 tests, ~4s
./.venv/bin/pytest tests/test_engine.py -k lookthrough   # single test
./.venv/bin/uvicorn app.main:app --reload

# Frontend
cd frontend
npm run build                      # tsc -b && vite build — type-check + build
npm run dev                        # vite dev server
```

**There is no `npm test` and no `npm run lint`.** See §6 — this is the repo's real gap, not an oversight to work around. Do not claim frontend tests pass; there is nothing to run.

Test conventions: pytest in `backend/tests/`, one file per module, fixtures in `conftest.py`. When frontend tests land, colocate as `*.test.tsx`.

## 5. Conventions & key decisions

Settled. Don't re-litigate without a reason:

- **Providers behind interfaces.** Every external data source (broker, market data, ETF holdings) sits behind a protocol in `providers/base.py`. This is what makes the app testable without network access — `mock_broker.py` and `seed.py` are why 47 tests run in 4 seconds.
- **SQLite now, Postgres later.** `config.py` defaults to `sqlite:///./portfolio.db`; `session.py` is written so `DATABASE_URL` can point at Postgres without touching call sites. The `db:` service in `docker-compose.yml` is **commented out** and intended for phase 3+.
- **Analytics are pure.** `engine.py` and `factors.py` take data and return numbers — no I/O, no DB, no HTTP. Keep it that way; it's why they're unit-testable.
- **Factor scores return `None`, not 0.** Missing data is not a neutral score. `_clamp` bounds real values; absent inputs propagate as `None` so the UI can distinguish "no data" from "average."
- **Pydantic models are the API contract.** `models.py` and `frontend/src/api.ts` must change together.

## 6. Known gap — frontend has no test or lint infrastructure

Deliberately recorded, not hidden:

| | Backend | Frontend |
|---|---|---|
| Test runner | pytest 8.3.3 | **none** |
| Test files | 6 files, 47 tests | **0** |
| Linter | – | **none** |
| Scripts | – | `dev`, `build`, `preview` only |

`~/.claude/CLAUDE.md` mandates test-first for input→output contract work, and portfolio math is exactly that shape. The backend honours it. **The frontend cannot**, because there's nothing to run a test with — and this is an app that renders financial analytics and is being wired to live brokerage accounts via Plaid.

Until Vitest + React Testing Library + ESLint are added, frontend changes get the `~/Projects/AGENTS.md` local-testing table (render it, exercise it, check empty/loading/error, verify one chart number by hand) and that is the **only** evidence available. Say so plainly rather than implying test coverage.

## 7. Gotchas

- **README says "Database: PostgreSQL" — it isn't.** The app runs on SQLite (`backend/portfolio.db`); the Postgres compose service is commented out and the README's tech-stack table describes the phase-3 target, not today. Trust `config.py` over the README. (2026-08-25)
- **A moved `.venv` is broken, not stale** — `bin/activate` hardcodes an absolute `VIRTUAL_ENV`. After any directory move, `rm -rf .venv && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt`. The repo moved from `~/Downloads` on 2026-08-25 and this bit. (2026-08-25)
- **`npm run build` is a type-check, not a test.** `tsc -b && vite build` proves it compiles. It says nothing about whether a number on screen is correct. (2026-08-25)
- **Plaid: sandbox credentials only on this machine.** Never put production Plaid keys in `.env` locally. Tokens must never be logged — `plaid_mapping.py` and `services/sync.py` are where an accidental `print` would leak one.
- **`.env.example` must change in the same commit as a new setting**, or the next clone fails with a confusing pydantic-settings validation error rather than a missing-variable message.
- **`backend/portfolio.db` is gitignored and local.** Schema changes have no migration tooling yet — deleting the file and letting it recreate is the current answer, which also destroys local data.
