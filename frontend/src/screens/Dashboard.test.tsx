import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanyExposure, PortfolioSummary, RiskMetrics } from "../api";
import { Dashboard } from "./Dashboard";

vi.mock("../api", () => ({
  api: {
    summary: vi.fn(),
    companies: vi.fn(),
    risk: vi.fn(),
  },
}));

// Imported after the mock so `api` is the mocked object.
const { api } = await import("../api");

function renderDashboard() {
  // retry: false so the error-state assertion doesn't wait out three retries.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<Dashboard />, { wrapper });
}

const SUMMARY: PortfolioSummary = {
  net_worth: 142_000,
  total_invested: 130_000,
  num_accounts: 3,
  num_holdings: 12,
  allocation_by_account: [
    { label: "brokerage", value: 100_000, weight: 0.7042 },
    { label: "roth", value: 42_000, weight: 0.2958 },
  ],
  allocation_by_asset_type: [{ label: "etf", value: 142_000, weight: 1 }],
};

const COMPANIES: CompanyExposure[] = [
  {
    ticker: "NVDA",
    name: "NVIDIA Corp",
    value: 21_300,
    weight: 0.15,
    direct_value: 5_000,
    via_etf_value: 16_300,
    source_etfs: ["VOO", "QQQ"],
  },
  {
    ticker: "AAPL",
    name: "Apple Inc",
    value: 14_200,
    weight: 0.1,
    direct_value: 0,
    via_etf_value: 14_200,
    source_etfs: ["VOO"],
  },
];

const RISK: RiskMetrics = {
  beta: 1.07,
  annualized_volatility: 0.184,
  sharpe_ratio: 0.92,
  max_drawdown: -0.23,
};

function resolveAll() {
  vi.mocked(api.summary).mockResolvedValue(SUMMARY);
  vi.mocked(api.companies).mockResolvedValue(COMPANIES);
  vi.mocked(api.risk).mockResolvedValue(RISK);
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Dashboard", () => {
  it("shows a loading state before the queries settle", () => {
    // Never-resolving promises hold the component in its pending state.
    const pending = new Promise<never>(() => {});
    vi.mocked(api.summary).mockReturnValue(pending);
    vi.mocked(api.companies).mockReturnValue(pending);
    vi.mocked(api.risk).mockReturnValue(pending);

    renderDashboard();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows an error message when the summary request fails", async () => {
    vi.mocked(api.summary).mockRejectedValue(new Error("/portfolio/summary -> 500"));
    vi.mocked(api.companies).mockResolvedValue(COMPANIES);
    vi.mocked(api.risk).mockResolvedValue(RISK);

    renderDashboard();

    expect(await screen.findByText("Failed to load summary.")).toBeInTheDocument();
  });

  it("renders net worth and unrealized gain formatted as currency", async () => {
    resolveAll();
    renderDashboard();

    expect(await screen.findByText("$142,000")).toBeInTheDocument();
    expect(screen.getByText("$130,000")).toBeInTheDocument();
    // 142,000 - 130,000 = 12,000 gain, rendered with an explicit + sign.
    expect(screen.getByText("+$12,000 unrealized")).toBeInTheDocument();
  });

  it("renders account and holding counts, and beta from the risk query", async () => {
    resolveAll();
    renderDashboard();

    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(screen.getByText("12 positions")).toBeInTheDocument();
    expect(screen.getByText("1.07")).toBeInTheDocument();
    expect(screen.getByText("18.4% vol")).toBeInTheDocument();
  });

  it("lists top exposures with their look-through weights", async () => {
    resolveAll();
    renderDashboard();

    expect(await screen.findByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("NVIDIA Corp")).toBeInTheDocument();
    expect(screen.getByText("15.0%")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("10.0%")).toBeInTheDocument();
  });

  it("renders an em dash for beta when the risk query has no data", async () => {
    vi.mocked(api.summary).mockResolvedValue(SUMMARY);
    vi.mocked(api.companies).mockResolvedValue(COMPANIES);
    vi.mocked(api.risk).mockResolvedValue({
      beta: null,
      annualized_volatility: null,
      sharpe_ratio: null,
      max_drawdown: null,
    });

    renderDashboard();

    expect(await screen.findByText("—")).toBeInTheDocument();
  });

  it("renders an empty exposure list without crashing", async () => {
    vi.mocked(api.summary).mockResolvedValue({
      ...SUMMARY,
      net_worth: 0,
      total_invested: 0,
      num_accounts: 0,
      num_holdings: 0,
      allocation_by_account: [],
      allocation_by_asset_type: [],
    });
    vi.mocked(api.companies).mockResolvedValue([]);
    vi.mocked(api.risk).mockResolvedValue(RISK);

    renderDashboard();

    expect(await screen.findByText("Top True Exposures (look-through)")).toBeInTheDocument();
    // Net worth and total invested both read $0 on an empty portfolio.
    expect(screen.getAllByText("$0")).toHaveLength(2);
    expect(screen.queryByText("NVDA")).not.toBeInTheDocument();
  });
});
