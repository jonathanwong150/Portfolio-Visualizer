import { useEffect, useState } from "react";
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
  "factors",
  "overlap",
  "risk",
  "correlation",
];

const TYPE_LABELS: Record<string, string> = {
  brokerage: "Brokerage",
  roth: "Roth IRA",
  "401k": "401(k)",
};

export function Accounts() {
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const [linkToken, setLinkToken] = useState<string | null>(null);

  const invalidateAll = () =>
    DERIVED_QUERIES.forEach((key) => qc.invalidateQueries({ queryKey: [key] }));

  const exchange = useMutation({
    mutationFn: api.plaidExchange,
    onSuccess: () => {
      setLinkToken(null);
      invalidateAll();
    },
  });

  const sync = useMutation({ mutationFn: api.plaidSync, onSuccess: invalidateAll });

  const link = useMutation({
    mutationFn: api.plaidLink,
    onSuccess: (res) => setLinkToken(res.link_token),
  });

  const { open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess: (publicToken) => exchange.mutate(publicToken),
  });

  // Plaid Link can only be opened once its token has been handed to the SDK.
  useEffect(() => {
    if (linkToken && ready) open();
  }, [linkToken, ready, open]);

  if (accounts.isLoading) return <div className="text-muted">Loading…</div>;
  if (accounts.error) return <div className="text-danger">Failed to load accounts.</div>;

  const { plaid_configured, accounts: rows } = accounts.data!;
  const totalValue = rows.reduce((sum, a) => sum + a.value, 0);
  const totalHoldings = rows.reduce((sum, a) => sum + a.num_holdings, 0);

  return (
    <div className="space-y-5">
      {!plaid_configured && (
        <div className="bg-accentSoft text-accent rounded-2xl px-5 py-3 text-sm">
          Plaid not configured — using mock data.
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
            onClick={() => link.mutate()}
            disabled={!plaid_configured || link.isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-accent text-black disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {link.isPending ? "Opening…" : "Connect account"}
          </button>
          <button
            onClick={() => sync.mutate()}
            disabled={!plaid_configured || sync.isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-surface2 text-white disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {sync.isPending ? "Syncing…" : "Sync"}
          </button>
        </Card>
      </div>

      {sync.error && <div className="text-danger text-sm">Sync failed. Try again.</div>}

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
