// Typed API client for the Portfolio Visualizer backend.
// In dev, Vite proxies /api -> http://localhost:8000 (see vite.config.ts).

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export interface BreakdownSlice {
  label: string;
  value: number;
  weight: number;
}

export interface PortfolioSummary {
  net_worth: number;
  total_invested: number;
  num_accounts: number;
  num_holdings: number;
  allocation_by_account: BreakdownSlice[];
  allocation_by_asset_type: BreakdownSlice[];
}

export interface CompanyExposure {
  ticker: string;
  name: string;
  value: number;
  weight: number;
  direct_value: number;
  via_etf_value: number;
  source_etfs: string[];
}

export interface RiskMetrics {
  beta: number | null;
  annualized_volatility: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
}

export interface FactorTilt {
  factor: string;
  low_label: string;
  high_label: string;
  score: number;
  high_weight: number;
  low_weight: number;
}

export interface OverlapMatrix {
  etfs: string[];
  matrix: number[][];
}

export interface CorrelationMatrix {
  tickers: string[];
  matrix: number[][];
}

export type AccountType = "brokerage" | "roth" | "401k";

export interface AccountSummary {
  id: number;
  name: string;
  type: AccountType;
  institution: string | null;
  value: number;
  num_holdings: number;
  last_synced_at: string | null;
}

export interface AccountsResponse {
  plaid_configured: boolean;
  accounts: AccountSummary[];
}

export interface LinkTokenResponse {
  configured: boolean;
  link_token: string | null;
}

export interface SyncResult {
  accounts: number;
  holdings: number;
  snapshot_at: string;
}

export const api = {
  summary: () => get<PortfolioSummary>("/portfolio/summary"),
  companies: () => get<CompanyExposure[]>("/exposure/companies"),
  sectors: () => get<BreakdownSlice[]>("/exposure/sectors"),
  geography: () => get<BreakdownSlice[]>("/exposure/geography"),
  factors: () => get<FactorTilt[]>("/exposure/factors"),
  overlap: () => get<OverlapMatrix>("/overlap"),
  risk: () => get<RiskMetrics>("/risk/metrics"),
  correlation: () => get<CorrelationMatrix>("/risk/correlation"),
  accounts: () => get<AccountsResponse>("/accounts"),
  plaidLink: () => post<LinkTokenResponse>("/plaid/link"),
  plaidExchange: (public_token: string) =>
    post<{ item_id: string }>("/plaid/exchange", { public_token }),
  plaidSync: () => post<SyncResult>("/plaid/sync"),
};
