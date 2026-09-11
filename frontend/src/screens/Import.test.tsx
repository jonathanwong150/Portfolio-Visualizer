import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ParsedImport } from "../api";
import { Import } from "./Import";

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return {
    ...original,
    api: {
      ...original.api,
      importPreview: vi.fn(),
      importCommit: vi.fn(),
      coverage: vi.fn(),
    },
  };
});

const { api } = await import("../api");

function renderImport(props: React.ComponentProps<typeof Import> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<Import {...props} />, { wrapper });
}

const PREVIEW: ParsedImport = {
  source_format: "fidelity",
  accounts: [
    { name: "Individual", account_type: "brokerage", inferred: true },
    { name: "ROTH IRA", account_type: "roth", inferred: true },
  ],
  holdings: [
    {
      ticker: "NVDA",
      name: "NVIDIA CORP",
      shares: 40,
      account_name: "Individual",
      security_type: "stock",
      price: 182.5,
      value: 7300,
      cost_basis: 6000,
    },
    {
      ticker: "VTI",
      name: "VANGUARD TOTAL STOCK MARKET ETF",
      shares: 40,
      account_name: "ROTH IRA",
      security_type: "stock",
      price: 312.75,
      value: 12510,
      cost_basis: 9000,
    },
  ],
  skipped: [{ line: 9, raw: "BTC,Bitcoin,Buy,0.015", reason: "Crypto is not supported." }],
  warnings: ["GOOGL: a stock split appears in this history."],
};

function choose(file = new File(["ticker,shares\nNVDA,1\n"], "positions.csv")) {
  const input = screen.getByLabelText(/choose a csv/i);
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.coverage).mockResolvedValue({
    total_tickers: 0,
    with_prices: 0,
    with_metadata: 0,
    missing: [],
    etfs: [],
    configured: false,
  });
});

describe("Import", () => {
  it("prompts for a file before anything is uploaded", () => {
    renderImport();
    expect(screen.getByLabelText(/choose a csv/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("offers the canonical template as a download", () => {
    renderImport();
    const link = screen.getByRole("link", { name: /template/i });
    expect(link).toHaveAttribute("href", "/api/import/template.csv");
    expect(link).toHaveAttribute("download");
  });

  it("shows the parsed holdings after choosing a file", async () => {
    vi.mocked(api.importPreview).mockResolvedValue(PREVIEW);
    renderImport();
    choose();

    expect(await screen.findByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("VTI")).toBeInTheDocument();
    // The detected format is reported as a card heading, so you can tell the
    // file was understood as the right shape. Scoped, since the instructions
    // paragraph also mentions Fidelity.
    expect(
      screen.getByRole("heading", { name: /detected format: fidelity/i }),
    ).toBeInTheDocument();
  });

  it("surfaces the server's explanation when the file is unrecognised", async () => {
    vi.mocked(api.importPreview).mockRejectedValue(
      new Error("Could not find a recognisable header row."),
    );
    renderImport();
    choose();

    expect(await screen.findByText(/recognisable header row/i)).toBeInTheDocument();
  });

  it("shows skipped rows and warnings so nothing vanishes silently", async () => {
    vi.mocked(api.importPreview).mockResolvedValue(PREVIEW);
    renderImport();
    choose();

    expect(await screen.findByText(/crypto is not supported/i)).toBeInTheDocument();
    expect(screen.getByText(/stock split/i)).toBeInTheDocument();
  });

  it("lets an inferred account type be corrected before committing", async () => {
    vi.mocked(api.importPreview).mockResolvedValue(PREVIEW);
    vi.mocked(api.importCommit).mockResolvedValue({
      accounts: 2,
      holdings: 2,
      snapshot_at: "2026-08-28T12:00:00",
    });
    renderImport();
    choose();

    const select = await screen.findByLabelText("Account type for Individual");
    expect(select).toHaveValue("brokerage");
    fireEvent.change(select, { target: { value: "401k" } });

    fireEvent.click(screen.getByRole("button", { name: /import 2 holdings/i }));

    await waitFor(() => expect(api.importCommit).toHaveBeenCalled());
    const payload = vi.mocked(api.importCommit).mock.calls[0][0];
    const individual = payload.accounts.find((a) => a.name === "Individual");
    expect(individual?.account_type).toBe("401k");
    // The untouched account keeps its inferred value.
    expect(payload.accounts.find((a) => a.name === "ROTH IRA")?.account_type).toBe("roth");
  });

  it("confirms how much was imported on success", async () => {
    vi.mocked(api.importPreview).mockResolvedValue(PREVIEW);
    vi.mocked(api.importCommit).mockResolvedValue({
      accounts: 2,
      holdings: 2,
      snapshot_at: "2026-08-28T12:00:00",
    });
    renderImport();
    choose();

    fireEvent.click(await screen.findByRole("button", { name: /import 2 holdings/i }));

    expect(await screen.findByText(/imported 2 holdings across 2 accounts/i)).toBeInTheDocument();
  });

  it("offers a direct return to the portfolio after import", async () => {
    const onViewPortfolio = vi.fn();
    vi.mocked(api.importPreview).mockResolvedValue(PREVIEW);
    vi.mocked(api.importCommit).mockResolvedValue({
      accounts: 2,
      holdings: 2,
      snapshot_at: "2026-08-28T12:00:00",
    });
    renderImport({ onViewPortfolio });
    choose();

    fireEvent.click(await screen.findByRole("button", { name: /import 2 holdings/i }));
    fireEvent.click(await screen.findByRole("button", { name: "View portfolio" }));

    expect(onViewPortfolio).toHaveBeenCalledOnce();
  });

  it("reports a failed commit instead of claiming success", async () => {
    vi.mocked(api.importPreview).mockResolvedValue(PREVIEW);
    vi.mocked(api.importCommit).mockRejectedValue(new Error("Nothing to import."));
    renderImport();
    choose();

    fireEvent.click(await screen.findByRole("button", { name: /import 2 holdings/i }));

    expect(await screen.findByText(/nothing to import/i)).toBeInTheDocument();
  });

  it("does not offer to import when the file yielded no holdings", async () => {
    vi.mocked(api.importPreview).mockResolvedValue({
      ...PREVIEW,
      accounts: [],
      holdings: [],
    });
    renderImport();
    choose();

    expect(await screen.findByText(/no holdings/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^import/i })).not.toBeInTheDocument();
  });

  it("shows each holding's account so a mis-parsed file is obvious", async () => {
    vi.mocked(api.importPreview).mockResolvedValue(PREVIEW);
    renderImport();
    choose();

    const row = (await screen.findByText("NVDA")).closest("tr")!;
    expect(within(row).getByText("Individual")).toBeInTheDocument();
    expect(within(row).getByText("40")).toBeInTheDocument();
  });
});
