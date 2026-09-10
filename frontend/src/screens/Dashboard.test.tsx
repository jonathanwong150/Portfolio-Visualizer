import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CompanyExposure,
  NetWorthHistory,
  PortfolioSummary,
  RiskMetrics,
} from "../api";
import { Dashboard } from "./Dashboard";

// Only `api` is stubbed; the real exportUrls pass through, so the download
// assertions below verify the actual URLs rather than a copy of them.
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  api: {
    summary: vi.fn(),
    companies: vi.fn(),
    risk: vi.fn(),
    history: vi.fn(),
  },
}));

// Imported after the mock so `api` is the mocked object.
const { api } = await import("../api");

/** A titled Card, scoped so duplicate figures elsewhere don't collide. */
const card = (title: string) =>
  within(screen.getByRole("heading", { name: title }).parentElement!);

/** A Stat block, located by its label. */
const stat = (label: string) => within(screen.getByText(label).parentElement!);

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
    is_unresolved: false,
  },
  {
    ticker: "AAPL",
    name: "Apple Inc",
    value: 14_200,
    weight: 0.1,
    direct_value: 0,
    via_etf_value: 14_200,
    source_etfs: ["VOO"],
    is_unresolved: false,
  },
  {
    ticker: "UNRESOLVED:VOO",
    name: "Unresolved holdings in VOO",
    value: 71_000,
    weight: 0.5,
    direct_value: 0,
    via_etf_value: 71_000,
    source_etfs: ["VOO"],
    is_unresolved: true,
  },
];

const RISK: RiskMetrics = {
  beta: 1.07,
  annualized_volatility: 0.184,
  sharpe_ratio: 0.92,
  max_drawdown: -0.23,
};

const HISTORY: NetWorthHistory = {
  points: [
    { snapshot_at: "2024-01-01T12:00:00", net_worth: 130_000, num_holdings: 11 },
    { snapshot_at: "2024-02-01T12:00:00", net_worth: 142_000, num_holdings: 12 },
  ],
  prices_synthesized: true,
};

function resolveAll() {
  vi.mocked(api.summary).mockResolvedValue(SUMMARY);
  vi.mocked(api.companies).mockResolvedValue(COMPANIES);
  vi.mocked(api.risk).mockResolvedValue(RISK);
  vi.mocked(api.history).mockResolvedValue(HISTORY);
}

beforeEach(() => {
  vi.resetAllMocks();
  // Benign default so tests focused on other cards don't leave a queryFn
  // returning undefined, which react-query treats as an error.
  vi.mocked(api.history).mockResolvedValue({ points: [], prices_synthesized: false });
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

  it("does not present missing exposure data as an empty ranking", async () => {
    vi.mocked(api.summary).mockResolvedValue(SUMMARY);
    vi.mocked(api.companies).mockRejectedValue(new Error("/exposure/companies -> 500"));
    vi.mocked(api.risk).mockResolvedValue(RISK);

    renderDashboard();

    expect(await screen.findByText("Failed to load exposure.")).toBeInTheDocument();
    expect(screen.queryByText("Top Named Company Exposures (look-through)")).not.toBeInTheDocument();
  });

  it("renders net worth and unrealized gain formatted as currency", async () => {
    resolveAll();
    renderDashboard();

    // Scoped to the stat: the net-worth chart headlines the same figure.
    expect(await screen.findByText("Net Worth")).toBeInTheDocument();
    expect(stat("Net Worth").getByText("$142,000")).toBeInTheDocument();
    expect(stat("Total Invested").getByText("$130,000")).toBeInTheDocument();
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
    expect(screen.queryByText("UNRESOLVED:VOO")).not.toBeInTheDocument();
    expect(screen.getByText("50.0% unresolved")).toBeInTheDocument();
    expect(screen.getByText("$71,000 not attributed to named companies")).toBeInTheDocument();
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

  it("renders the net-worth chart from the history query", async () => {
    resolveAll();
    renderDashboard();

    expect(await screen.findByText("Net Worth Over Time")).toBeInTheDocument();
    // 142,000 - 130,000 = +12,000 over the two snapshots. Scoped to the chart
    // card, since the Total Invested stat also reads "+$12,000 unrealized".
    expect(card("Net Worth Over Time").getByText(/\+\$12,000 \(9\.2%\)/)).toBeInTheDocument();
    expect(card("Net Worth Over Time").getByText(/prototype/i)).toBeInTheDocument();
  });

  it("shows a scoped error when only the history query fails", async () => {
    vi.mocked(api.summary).mockResolvedValue(SUMMARY);
    vi.mocked(api.companies).mockResolvedValue(COMPANIES);
    vi.mocked(api.risk).mockResolvedValue(RISK);
    vi.mocked(api.history).mockRejectedValue(new Error("/portfolio/history -> 500"));

    renderDashboard();

    expect(await screen.findByText("Failed to load history.")).toBeInTheDocument();
    // The rest of the dashboard must still render.
    expect(screen.getByText("$142,000")).toBeInTheDocument();
  });

  it("offers both CSV exports as download links", async () => {
    resolveAll();
    renderDashboard();

    const holdings = await screen.findByRole("link", { name: /holdings/i });
    const exposure = screen.getByRole("link", { name: /exposure/i });

    expect(holdings).toHaveAttribute("href", "/api/export/holdings.csv");
    expect(holdings).toHaveAttribute("download");
    expect(exposure).toHaveAttribute("href", "/api/export/exposure.csv");
    expect(exposure).toHaveAttribute("download");
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

    expect(await screen.findByText("Top Named Company Exposures (look-through)")).toBeInTheDocument();
    expect(screen.getByText("No named company exposure yet.")).toBeInTheDocument();
    // Net worth and total invested both read $0 on an empty portfolio.
    expect(screen.getAllByText("$0")).toHaveLength(2);
    expect(screen.queryByText("NVDA")).not.toBeInTheDocument();
  });

  it("explains when the portfolio is entirely unresolved", async () => {
    vi.mocked(api.summary).mockResolvedValue(SUMMARY);
    vi.mocked(api.companies).mockResolvedValue([COMPANIES[2]]);
    vi.mocked(api.risk).mockResolvedValue(RISK);

    renderDashboard();

    expect(await screen.findByText("No named company exposure yet.")).toBeInTheDocument();
    expect(screen.getByText("50.0% unresolved")).toBeInTheDocument();
  });
});
