# Portfolio Visualizer

A responsive web app that aggregates your investment holdings across accounts
(brokerage / Roth / 401k), performs **ETF look-through** to reveal your *true*
company exposure, and computes sector / factor / risk analytics.

> **Not financial advice.** This tool is for visualization and analysis only.

## Why

As an intermediate investor holding many ETFs and individual stocks across
multiple accounts, it's hard to answer questions like:

- How much of my portfolio is *actually* NVIDIA (across every fund + direct holdings)?
- How much do my ETFs overlap with each other?
- Am I overexposed to growth / large-cap / a single sector?
- What are my real risk characteristics (beta, volatility, Sharpe, drawdown)?

## Features (by phase)

- **Phase 1 (MVP):** Holdings ingest (mock broker) → ETF look-through → true
  company exposure, sector breakdown, portfolio beta. Dashboard + Exposure UI.
- **Phase 2:** ETF overlap, factor tilts (growth/value/size/momentum/quality),
  full risk suite (volatility, Sharpe, max drawdown), correlation matrix.
- **Phase 3:** Live broker sync via Plaid (brokerage/Roth/401k), snapshots.
- **Phase 4:** Paid data upgrades, historical net-worth tracking, export/share.
- **Phase 5:** Native mobile app (React Native) reusing the same backend.

## Tech Stack

| Layer     | Choice                                                        |
|-----------|--------------------------------------------------------------|
| Frontend  | React + TypeScript + Vite, Tailwind CSS, Recharts / visx     |
| Backend   | Python + FastAPI, pandas / numpy                             |
| Database  | PostgreSQL                                                   |
| Broker    | Plaid Investments (behind a `BrokerAdapter` interface)       |
| Market    | yfinance (behind a `MarketDataProvider` interface)          |
| ETF data  | Curated seed dataset (behind an `ETFHoldingsProvider`)      |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design.

## Quick Start

```bash
# Backend (from repo root)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Or with Docker:

```bash
docker compose up --build
```

- API:      http://localhost:8000  (docs at `/docs`)
- Frontend: http://localhost:5173
