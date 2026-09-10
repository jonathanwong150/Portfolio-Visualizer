import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Accounts } from "./Accounts";

const plaid = vi.hoisted(() => ({
  open: vi.fn(),
  error: null as ErrorEvent | null,
  options: undefined as
    | {
        onSuccess: (publicToken: string) => void;
        onExit: (error: { display_message?: string } | null) => void;
      }
    | undefined,
}));

vi.mock("react-plaid-link", () => ({
  usePlaidLink: vi.fn((options) => {
    plaid.options = options;
    return { error: plaid.error, open: plaid.open, ready: true };
  }),
}));

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return {
    ...original,
    api: {
      ...original.api,
      accounts: vi.fn(),
      plaidLink: vi.fn(),
      plaidExchange: vi.fn(),
      plaidSync: vi.fn(),
    },
  };
});

const { api } = await import("../api");

function renderAccounts(props: React.ComponentProps<typeof Accounts> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { ...render(<Accounts {...props} />, { wrapper }), client };
}

const SYNCED = {
  accounts: 1,
  holdings: 3,
  snapshot_at: "2026-09-09T12:00:00",
};

beforeEach(() => {
  vi.clearAllMocks();
  plaid.options = undefined;
  plaid.error = null;
  vi.mocked(api.accounts).mockResolvedValue({ plaid_configured: true, accounts: [] });
  vi.mocked(api.plaidLink).mockResolvedValue({ configured: true, link_token: "link-token" });
  vi.mocked(api.plaidExchange).mockResolvedValue({ item_id: "item" });
  vi.mocked(api.plaidSync).mockResolvedValue(SYNCED);
});

describe("Accounts", () => {
  it("exchanges, automatically syncs, refreshes every derived query, and returns", async () => {
    let resolveSync!: (value: typeof SYNCED) => void;
    vi.mocked(api.plaidSync).mockReturnValue(
      new Promise((resolve) => {
        resolveSync = resolve;
      }),
    );
    const onViewPortfolio = vi.fn();
    const { client } = renderAccounts({ onViewPortfolio });
    const invalidate = vi.spyOn(client, "invalidateQueries");

    fireEvent.click(await screen.findByRole("button", { name: "Connect account" }));
    await waitFor(() => expect(plaid.open).toHaveBeenCalledOnce());
    act(() => plaid.options!.onSuccess("public-token"));

    await waitFor(() => expect(api.plaidExchange).toHaveBeenCalledOnce());
    expect(vi.mocked(api.plaidExchange).mock.calls[0][0]).toBe("public-token");
    await waitFor(() => expect(api.plaidSync).toHaveBeenCalledOnce());
    expect(onViewPortfolio).not.toHaveBeenCalled();
    await act(async () => resolveSync(SYNCED));

    expect(await screen.findByText(/synced 3 holdings/i)).toBeInTheDocument();
    await waitFor(() => expect(onViewPortfolio).toHaveBeenCalledOnce());
    const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey?.[0]);
    expect(keys).toEqual(expect.arrayContaining([
      "accounts",
      "summary",
      "companies",
      "sectors",
      "geography",
      "factors",
      "overlap",
      "risk",
      "correlation",
      "history",
      "coverage",
    ]));
  });

  it("retries a failed link-token request", async () => {
    vi.mocked(api.plaidLink)
      .mockRejectedValueOnce(new Error("Token service unavailable"))
      .mockResolvedValueOnce({ configured: true, link_token: "retry-token" });
    renderAccounts();

    fireEvent.click(await screen.findByRole("button", { name: "Connect account" }));
    expect(await screen.findByText(/could not start bank connection/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));

    await waitFor(() => expect(api.plaidLink).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(plaid.open).toHaveBeenCalledOnce());
  });

  it("surfaces exchange failure without syncing and can retry exchange", async () => {
    vi.mocked(api.plaidExchange)
      .mockRejectedValueOnce(new Error("Exchange failed"))
      .mockResolvedValueOnce({ item_id: "item" });
    renderAccounts();
    fireEvent.click(await screen.findByRole("button", { name: "Connect account" }));
    await waitFor(() => expect(plaid.open).toHaveBeenCalledOnce());
    act(() => plaid.options!.onSuccess("public-token"));

    expect(await screen.findByText(/could not finish linking/i)).toBeInTheDocument();
    expect(api.plaidSync).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry exchange" }));

    await waitFor(() => expect(api.plaidExchange).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.plaidSync).toHaveBeenCalledOnce());
  });

  it("disables exchange retry while a manual sync is pending", async () => {
    vi.mocked(api.plaidExchange).mockRejectedValue(new Error("Exchange failed"));
    vi.mocked(api.plaidSync).mockReturnValue(new Promise(() => {}));
    renderAccounts();
    fireEvent.click(await screen.findByRole("button", { name: "Connect account" }));
    await waitFor(() => expect(plaid.open).toHaveBeenCalledOnce());
    act(() => plaid.options!.onSuccess("public-token"));
    expect(await screen.findByRole("button", { name: "Retry exchange" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Sync" }));

    expect(screen.getByRole("button", { name: "Retry exchange" })).toBeDisabled();
  });

  it("disables connection retry while a manual sync is pending", async () => {
    vi.mocked(api.plaidLink).mockRejectedValue(new Error("Token failed"));
    vi.mocked(api.plaidSync).mockReturnValue(new Promise(() => {}));
    renderAccounts();
    fireEvent.click(await screen.findByRole("button", { name: "Connect account" }));
    expect(await screen.findByRole("button", { name: "Retry connection" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Sync" }));

    expect(screen.getByRole("button", { name: "Retry connection" })).toBeDisabled();
  });

  it("retries only sync after a successful exchange", async () => {
    vi.mocked(api.plaidSync)
      .mockRejectedValueOnce(new Error("Holdings unavailable"))
      .mockResolvedValueOnce(SYNCED);
    const onViewPortfolio = vi.fn();
    renderAccounts({ onViewPortfolio });
    fireEvent.click(await screen.findByRole("button", { name: "Connect account" }));
    await waitFor(() => expect(plaid.open).toHaveBeenCalledOnce());
    act(() => plaid.options!.onSuccess("public-token"));

    expect(await screen.findByText(/account linked, but holdings did not sync/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry sync" }));

    await waitFor(() => expect(api.plaidSync).toHaveBeenCalledTimes(2));
    expect(api.plaidExchange).toHaveBeenCalledOnce();
    await waitFor(() => expect(onViewPortfolio).toHaveBeenCalledOnce());
  });

  it("cleans up a canceled Link session without reopening it", async () => {
    renderAccounts();
    fireEvent.click(await screen.findByRole("button", { name: "Connect account" }));
    await waitFor(() => expect(plaid.open).toHaveBeenCalledOnce());
    act(() => plaid.options!.onExit(null));

    expect(await screen.findByText(/connection canceled/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect account" })).toBeEnabled();
    expect(plaid.open).toHaveBeenCalledOnce();
  });

  it("surfaces an SDK load failure and releases the connection controls", async () => {
    const view = renderAccounts();
    fireEvent.click(await screen.findByRole("button", { name: "Connect account" }));
    await waitFor(() => expect(plaid.open).toHaveBeenCalledOnce());

    plaid.error = new ErrorEvent("error", { message: "Plaid SDK unavailable" });
    view.rerender(<Accounts />);

    expect(await screen.findByText(/could not load bank connection.*sdk unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect account" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Retry connection" })).toBeEnabled();
  });

  it("keeps manual sync and reports success without navigating", async () => {
    const onViewPortfolio = vi.fn();
    renderAccounts({ onViewPortfolio });

    fireEvent.click(await screen.findByRole("button", { name: "Sync" }));

    expect(await screen.findByText(/synced 3 holdings/i)).toBeInTheDocument();
    expect(api.plaidSync).toHaveBeenCalledOnce();
    expect(onViewPortfolio).not.toHaveBeenCalled();
  });

  it("explains unavailable linking and offers CSV import", async () => {
    const onImport = vi.fn();
    vi.mocked(api.accounts).mockResolvedValue({ plaid_configured: false, accounts: [] });
    renderAccounts({ onImport });

    expect(await screen.findByText(/bank linking is unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/using mock data/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import CSV" }));
    expect(onImport).toHaveBeenCalledOnce();
  });
});
