import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("react-plaid-link", () => ({
  usePlaidLink: vi.fn(() => ({ open: vi.fn(), ready: false })),
}));

vi.mock("./api", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api")>();
  return {
    ...original,
    api: {
      ...original.api,
      summary: vi.fn(),
      companies: vi.fn(),
      risk: vi.fn(),
      history: vi.fn(),
      accounts: vi.fn(),
      coverage: vi.fn(),
    },
  };
});

const { api } = await import("./api");

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<App />, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.summary).mockResolvedValue({
    data_status: "demo",
    net_worth: 1000,
    total_invested: 900,
    num_accounts: 1,
    num_holdings: 1,
    allocation_by_account: [],
    allocation_by_asset_type: [],
  });
  vi.mocked(api.companies).mockResolvedValue([]);
  vi.mocked(api.risk).mockResolvedValue({
    beta: null,
    annualized_volatility: null,
    sharpe_ratio: null,
    max_drawdown: null,
  });
  vi.mocked(api.history).mockResolvedValue({ points: [], prices_synthesized: true });
  vi.mocked(api.accounts).mockResolvedValue({ plaid_configured: true, accounts: [] });
  vi.mocked(api.coverage).mockResolvedValue({
    total_tickers: 0,
    with_prices: 0,
    with_metadata: 0,
    missing: [],
    etfs: [],
    configured: false,
  });
});

describe("App onboarding navigation", () => {
  it("routes the Dashboard connect action to Accounts", async () => {
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "Connect account" }));
    expect(await screen.findByRole("heading", { name: "Connected Accounts" })).toBeInTheDocument();
  });

  it("routes the Dashboard import action to Import", async () => {
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "Import CSV" }));
    expect(await screen.findByRole("heading", { name: "Import holdings" })).toBeInTheDocument();
  });
});
