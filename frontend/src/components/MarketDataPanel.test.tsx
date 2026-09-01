import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Coverage } from "../api";
import { MarketDataPanel } from "./MarketDataPanel";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  api: { coverage: vi.fn(), refreshMarketData: vi.fn() },
}));

const { api } = await import("../api");

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<MarketDataPanel />, { wrapper });
}

const FULL: Coverage = {
  total_tickers: 20,
  with_prices: 20,
  with_metadata: 20,
  missing: [],
  etfs: [{ ticker: "VT", constituents: 314, covered_weight: 0.53 }],
  configured: true,
};

const PARTIAL: Coverage = {
  total_tickers: 20,
  with_prices: 11,
  with_metadata: 9,
  missing: ["NVDA", "PLTR", "VOO"],
  etfs: [],
  configured: true,
};

beforeEach(() => {
  vi.resetAllMocks();
});

describe("MarketDataPanel", () => {
  it("reports how many tickers have real prices", async () => {
    vi.mocked(api.coverage).mockResolvedValue(PARTIAL);
    renderPanel();
    expect(await screen.findByText(/11 of 20/)).toBeInTheDocument();
  });

  it("names the tickers still missing prices", async () => {
    vi.mocked(api.coverage).mockResolvedValue(PARTIAL);
    renderPanel();
    expect(await screen.findByText(/NVDA/)).toBeInTheDocument();
    expect(screen.getByText(/PLTR/)).toBeInTheDocument();
  });

  it("warns that figures are estimated while coverage is incomplete", async () => {
    vi.mocked(api.coverage).mockResolvedValue(PARTIAL);
    renderPanel();
    expect(await screen.findByText(/estimated/i)).toBeInTheDocument();
  });

  it("stops warning once every ticker is covered", async () => {
    vi.mocked(api.coverage).mockResolvedValue(FULL);
    renderPanel();
    await screen.findByText(/20 of 20/);
    expect(screen.queryByText(/estimated/i)).not.toBeInTheDocument();
  });

  it("shows how much of each ETF its constituents cover", async () => {
    vi.mocked(api.coverage).mockResolvedValue(FULL);
    renderPanel();
    // 314 names covering 53% — the number that says how far to trust a
    // look-through percentage.
    expect(await screen.findByText(/314/)).toBeInTheDocument();
    expect(screen.getByText(/53(\.0)?%/)).toBeInTheDocument();
  });

  it("tells you to add a key when none is configured", async () => {
    vi.mocked(api.coverage).mockResolvedValue({ ...PARTIAL, configured: false });
    renderPanel();
    expect(await screen.findByText(/ALPHAVANTAGE_API_KEY/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /refresh/i })).toBeDisabled();
  });

  it("reports the daily cap plainly when throttled", async () => {
    vi.mocked(api.coverage).mockResolvedValue(PARTIAL);
    vi.mocked(api.refreshMarketData).mockResolvedValue({
      tickers_seen: 20,
      tickers_refreshed: 7,
      calls_made: 25,
      already_fresh: 5,
      still_stale: 8,
      stopped_early: false,
      throttled: true,
      messages: ["Alpha Vantage's free tier allows 25 requests per day"],
    });
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: /refresh/i }));

    expect(await screen.findByText(/25 requests per day/)).toBeInTheDocument();
    expect(screen.getByText(/refreshed 7/i)).toBeInTheDocument();
  });

  it("surfaces a failed refresh instead of looking successful", async () => {
    vi.mocked(api.coverage).mockResolvedValue(PARTIAL);
    vi.mocked(api.refreshMarketData).mockRejectedValue(
      new Error("ALPHAVANTAGE_API_KEY is not set"),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: /refresh/i }));

    expect(await screen.findByText(/is not set/)).toBeInTheDocument();
  });

  it("disables the button while a refresh is in flight", async () => {
    vi.mocked(api.coverage).mockResolvedValue(PARTIAL);
    vi.mocked(api.refreshMarketData).mockReturnValue(new Promise(() => {}));
    renderPanel();

    const button = await screen.findByRole("button", { name: /refresh/i });
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
  });
});
