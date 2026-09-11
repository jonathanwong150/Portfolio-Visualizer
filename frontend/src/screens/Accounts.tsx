import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePlaidLink } from "react-plaid-link";
import { AccountSummary, api } from "../api";
import { Card, Stat } from "../components/Card";
import { usd } from "../format";

// Every analytics query is derived from holdings, so a sync invalidates them all.
const DERIVED_QUERIES = [
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
];

const TYPE_LABELS: Record<string, string> = {
  brokerage: "Brokerage",
  roth: "Roth IRA",
  "401k": "401(k)",
};

interface AccountsProps {
  onImport?: () => void;
  onViewPortfolio?: () => void;
}

export function Accounts({ onImport, onViewPortfolio }: AccountsProps) {
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [linkProblem, setLinkProblem] = useState<string | null>(null);
  const [sdkProblem, setSdkProblem] = useState<string | null>(null);
  const [linkExit, setLinkExit] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const openedToken = useRef<string | null>(null);
  const returnAfterSync = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      returnAfterSync.current = false;
    };
  }, []);

  const invalidateAll = () =>
    Promise.all(
      DERIVED_QUERIES.map((key) => qc.invalidateQueries({ queryKey: [key] })),
    );

  const sync = useMutation({
    mutationFn: api.plaidSync,
    onSuccess: async (result) => {
      if (mounted.current) {
        setSuccess(
          `Synced ${result.holdings} holdings across ${result.accounts} accounts.`,
        );
      }
      await invalidateAll();
      if (mounted.current && returnAfterSync.current) {
        returnAfterSync.current = false;
        onViewPortfolio?.();
      }
    },
  });

  const exchange = useMutation({
    mutationFn: api.plaidExchange,
    onSuccess: () => {
      setLinkToken(null);
      returnAfterSync.current = true;
      sync.mutate();
    },
  });

  const link = useMutation({
    mutationFn: api.plaidLink,
    onSuccess: (res) => {
      if (!res.configured || !res.link_token) {
        setLinkProblem("Bank linking is not configured.");
        return;
      }
      setLinkToken(res.link_token);
    },
  });

  const { error: plaidError, open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess: (token) => {
      setLinkToken(null);
      exchange.reset();
      exchange.mutate(token);
    },
    onExit: (error) => {
      setLinkToken(null);
      openedToken.current = null;
      setLinkExit(
        error
          ? `Bank connection closed: ${error.display_message ?? "please try again."}`
          : "Connection canceled. No account was added.",
      );
    },
  });

  // Plaid Link can only be opened once its token has been handed to the SDK.
  useEffect(() => {
    if (linkToken && ready && openedToken.current !== linkToken) {
      openedToken.current = linkToken;
      open();
    }
  }, [linkToken, ready, open]);

  useEffect(() => {
    if (!linkToken || !plaidError) return;
    setLinkToken(null);
    openedToken.current = null;
    setSdkProblem(
      `Could not load bank connection. ${plaidError.message || "Please try again."}`,
    );
  }, [linkToken, plaidError]);

  const startLink = () => {
    if (sdkProblem) return;
    setSuccess(null);
    setLinkProblem(null);
    setLinkExit(null);
    setLinkToken(null);
    openedToken.current = null;
    returnAfterSync.current = false;
    link.reset();
    exchange.reset();
    sync.reset();
    link.mutate();
  };

  const startManualSync = () => {
    setSuccess(null);
    returnAfterSync.current = false;
    sync.reset();
    sync.mutate();
  };

  if (accounts.isLoading) return <div className="text-muted">Loading…</div>;
  if (accounts.error) return <div className="text-danger">Failed to load accounts.</div>;

  const { plaid_configured, accounts: rows } = accounts.data!;
  const totalValue = rows.reduce((sum, a) => sum + a.value, 0);
  const totalHoldings = rows.reduce((sum, a) => sum + a.num_holdings, 0);
  const busy =
    link.isPending || Boolean(linkToken) || exchange.isPending || sync.isPending;
  const connectLabel = link.isPending || linkToken
    ? "Opening…"
    : exchange.isPending
      ? "Linking…"
      : "Connect account";

  return (
    <div className="space-y-5">
      {!plaid_configured && (
        <div className="bg-accentSoft text-accent rounded-2xl px-5 py-3 text-sm">
          <p>
            Bank linking is unavailable in this environment. You can still add real
            holdings from a CSV.
          </p>
          <button
            type="button"
            onClick={onImport}
            className="mt-2 rounded-lg bg-accent px-3 py-1.5 font-semibold text-black"
          >
            Import CSV
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <Card>
          <Stat label="Connected Value" value={usd(totalValue)} />
        </Card>
        <Card>
          <Stat
            label="Accounts"
            value={String(rows.length)}
            sub={`${totalHoldings} positions`}
          />
        </Card>
        <Card className="flex items-center gap-3">
          <button
            onClick={startLink}
            disabled={!plaid_configured || busy || Boolean(sdkProblem)}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-accent text-black disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {connectLabel}
          </button>
          <button
            onClick={startManualSync}
            disabled={!plaid_configured || busy}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-surface2 text-white disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {sync.isPending ? "Syncing…" : "Sync"}
          </button>
        </Card>
      </div>

      {(link.error || linkProblem) && (
        <FlowError
          message={`Could not start bank connection. ${link.error?.message ?? linkProblem}`}
          retryLabel="Retry connection"
          onRetry={startLink}
          disabled={busy}
        />
      )}
      {sdkProblem && <ReloadError message={sdkProblem} />}
      {exchange.error && (
        <FlowError
          message={`Could not finish linking. ${exchange.error.message} A public token can only be used once, so restart connection to try again. If the exchange may have succeeded before its response was lost, Sync can recover it.`}
          retryLabel="Restart connection"
          onRetry={startLink}
          disabled={busy}
        />
      )}
      {sync.error && (
        <FlowError
          message={
            returnAfterSync.current
              ? `Account linked, but holdings did not sync. ${sync.error.message}`
              : `Holdings did not sync. ${sync.error.message}`
          }
          retryLabel="Retry sync"
          onRetry={() => {
            if (!busy) sync.mutate();
          }}
          disabled={busy}
        />
      )}
      {linkExit && <div className="text-warning text-sm">{linkExit}</div>}
      {success && <div className="text-accent text-sm">{success}</div>}

      <Card title="Connected Accounts">
        {rows.length === 0 ? (
          <p className="text-muted text-sm">
            No accounts synced yet. Connect a brokerage to pull in live holdings.
          </p>
        ) : (
          <ul className="space-y-3">
            {rows.map((a) => (
              <AccountRow key={a.id} account={a} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function ReloadError({ message }: { message: string }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-danger text-sm">
      <span>{message}</span>
      <a
        href={window.location.href}
        className="rounded-lg bg-surface2 px-3 py-1.5 font-medium text-white"
      >
        Reload page
      </a>
    </div>
  );
}

function FlowError({
  message,
  retryLabel,
  onRetry,
  disabled,
}: {
  message: string;
  retryLabel: string;
  onRetry: () => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-danger text-sm">
      <span>{message}</span>
      <button
        type="button"
        onClick={onRetry}
        disabled={disabled}
        className="rounded-lg bg-surface2 px-3 py-1.5 font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
      >
        {retryLabel}
      </button>
    </div>
  );
}

function AccountRow({ account }: { account: AccountSummary }) {
  return (
    <li className="flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{account.name}</div>
        <div className="text-xs text-muted">
          {account.institution ?? "—"} · {account.num_holdings} positions
        </div>
      </div>
      <span className="px-2 py-0.5 rounded-md bg-accentSoft text-accent text-xs font-medium">
        {TYPE_LABELS[account.type] ?? account.type}
      </span>
      <span className="font-semibold w-28 text-right">{usd(account.value)}</span>
    </li>
  );
}
