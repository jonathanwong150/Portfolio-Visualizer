import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanyExposure } from "../api";
import { Exposure } from "./Exposure";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  api: { companies: vi.fn(), sectors: vi.fn() },
}));

const { api } = await import("../api");

const EXPOSURES: CompanyExposure[] = [
  {
    ticker: "AAPL",
    name: "Apple Inc",
    value: 300,
    weight: 0.3,
    direct_value: 100,
    via_etf_value: 200,
    source_etfs: ["TOY"],
    is_unresolved: false,
  },
  {
    ticker: "UNRESOLVED:TOY",
    name: "Unresolved holdings in TOY",
    value: 700,
    weight: 0.7,
    direct_value: 0,
    via_etf_value: 700,
    source_etfs: ["TOY"],
    is_unresolved: true,
  },
];

function renderExposure() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<Exposure />, { wrapper });
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.companies).mockResolvedValue(EXPOSURES);
  vi.mocked(api.sectors).mockResolvedValue([
    { label: "Technology", value: 300, weight: 0.3 },
    { label: "Unknown", value: 700, weight: 0.7 },
  ]);
});

describe("Exposure", () => {
  it("shows loading while company exposure is pending", () => {
    vi.mocked(api.companies).mockReturnValue(new Promise<never>(() => {}));

    renderExposure();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("does not present a failed company request as no matches", async () => {
    vi.mocked(api.companies).mockRejectedValue(new Error("/exposure/companies -> 500"));

    renderExposure();

    expect(await screen.findByText("Failed to load company exposure.")).toBeInTheDocument();
    expect(screen.queryByText("No matches.")).not.toBeInTheDocument();
  });

  it("shows a scoped sector error while retaining company exposure", async () => {
    vi.mocked(api.sectors).mockRejectedValue(new Error("/exposure/sectors -> 500"));

    renderExposure();

    expect(await screen.findByText("Failed to load sector exposure.")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("70.0% unresolved")).toBeInTheDocument();
  });

  it("renders an honest empty state", async () => {
    vi.mocked(api.companies).mockResolvedValue([]);
    vi.mocked(api.sectors).mockResolvedValue([]);

    renderExposure();

    expect(await screen.findByText("No sector exposure.")).toBeInTheDocument();
    expect(screen.getByText("No matches.")).toBeInTheDocument();
    expect(screen.queryByTestId("unresolved-exposure")).not.toBeInTheDocument();
  });

  it("separates unresolved ETF value from the named company ranking", async () => {
    renderExposure();

    const unresolved = within(await screen.findByTestId("unresolved-exposure"));
    expect(unresolved.getByText("70.0% unresolved")).toBeInTheDocument();
    expect(unresolved.getByText("$700")).toBeInTheDocument();
    expect(unresolved.getByText("Unresolved holdings in TOY")).toBeInTheDocument();

    const companies = within(screen.getByTestId("named-company-exposure"));
    expect(companies.getByText("AAPL")).toBeInTheDocument();
    expect(companies.queryByText("UNRESOLVED:TOY")).not.toBeInTheDocument();
  });
});
