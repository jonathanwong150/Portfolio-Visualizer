import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  api,
  exportUrls,
  type AccountType,
  type ParsedAccount,
  type ParsedImport,
} from "../api";
import { Card } from "../components/Card";
import { usd } from "../format";

const ACCOUNT_TYPES: AccountType[] = ["brokerage", "roth", "401k"];

const TYPE_LABELS: Record<AccountType, string> = {
  brokerage: "Taxable brokerage",
  roth: "Roth IRA",
  "401k": "401(k)",
};

export function Import() {
  const queryClient = useQueryClient();
  const [preview, setPreview] = useState<ParsedImport | null>(null);
  const [accounts, setAccounts] = useState<ParsedAccount[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setDone(null);
    setPreview(null);
    setBusy(true);
    try {
      const parsed = await api.importPreview(file);
      setPreview(parsed);
      setAccounts(parsed.accounts);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read that file.");
    } finally {
      setBusy(false);
    }
  }

  function setAccountType(name: string, account_type: AccountType) {
    setAccounts((current) =>
      current.map((a) => (a.name === name ? { ...a, account_type, inferred: false } : a)),
    );
  }

  async function commit() {
    if (!preview) return;
    setError(null);
    setBusy(true);
    try {
      const result = await api.importCommit({ holdings: preview.holdings, accounts });
      setDone(
        `Imported ${result.holdings} holdings across ${result.accounts} accounts.`,
      );
      setPreview(null);
      // Every screen reads holdings, so nothing cached is still valid.
      await queryClient.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card title="Import holdings">
        <p className="text-muted text-sm mb-4">
          Upload a positions export from Fidelity or Schwab, or a Robinhood transaction
          history (Account → Reports and statements → Download CSV). Nothing is saved
          until you review it below.
        </p>

        <div className="flex flex-wrap items-center gap-4">
          <label className="text-sm font-medium">
            <span className="block mb-1.5">Choose a CSV file</span>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => onFile(e.target.files?.[0])}
              className="text-sm text-muted file:mr-3 file:px-4 file:py-2 file:rounded-lg file:border-0 file:bg-accent/10 file:text-accent file:text-sm file:font-medium"
            />
          </label>
          <a
            href={exportUrls.template}
            download
            className="text-accent text-sm hover:underline self-end pb-1"
          >
            ↓ Download template
          </a>
        </div>

        {busy && <p className="text-muted text-sm mt-3">Working…</p>}
        {error && <p className="text-danger text-sm mt-3">{error}</p>}
        {done && <p className="text-accent text-sm mt-3">{done}</p>}
      </Card>

      {preview && <Preview preview={preview} accounts={accounts} onType={setAccountType} onCommit={commit} busy={busy} />}
    </div>
  );
}

function Preview({
  preview,
  accounts,
  onType,
  onCommit,
  busy,
}: {
  preview: ParsedImport;
  accounts: ParsedAccount[];
  onType: (name: string, type: AccountType) => void;
  onCommit: () => void;
  busy: boolean;
}) {
  const total = preview.holdings.reduce((sum, h) => sum + (h.value ?? 0), 0);

  return (
    <>
      <Card title={`Detected format: ${preview.source_format}`}>
        {preview.holdings.length === 0 ? (
          <p className="text-muted text-sm">
            No holdings were found in that file. Check you exported positions rather than
            a summary, or use the template.
          </p>
        ) : (
          <>
            {accounts.length > 0 && (
              <div className="space-y-3 mb-5">
                <p className="text-muted text-xs uppercase tracking-wide">
                  Confirm account types
                </p>
                {accounts.map((account) => (
                  <div key={account.name} className="flex items-center gap-3 flex-wrap">
                    <label
                      htmlFor={`type-${account.name}`}
                      className="text-sm font-medium min-w-40"
                    >
                      {account.name}
                    </label>
                    <select
                      id={`type-${account.name}`}
                      aria-label={`Account type for ${account.name}`}
                      value={account.account_type}
                      onChange={(e) => onType(account.name, e.target.value as AccountType)}
                      className="bg-surface border border-white/10 rounded-lg px-3 py-1.5 text-sm"
                    >
                      {ACCOUNT_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {TYPE_LABELS[t]}
                        </option>
                      ))}
                    </select>
                    {account.inferred && (
                      <span className="text-muted text-xs">guessed from the name</span>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-muted text-xs uppercase tracking-wide text-left">
                    <th className="pb-2">Ticker</th>
                    <th className="pb-2">Name</th>
                    <th className="pb-2">Account</th>
                    <th className="pb-2 text-right">Shares</th>
                    <th className="pb-2 text-right">Price</th>
                    <th className="pb-2 text-right">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.holdings.map((h) => (
                    <tr key={`${h.account_name}-${h.ticker}`} className="border-t border-white/5">
                      <td className="py-1.5 font-medium">{h.ticker}</td>
                      <td className="py-1.5 text-muted truncate max-w-56">{h.name ?? "—"}</td>
                      <td className="py-1.5 text-muted">{h.account_name}</td>
                      <td className="py-1.5 text-right">{h.shares}</td>
                      <td className="py-1.5 text-right">{h.price != null ? usd(h.price) : "—"}</td>
                      <td className="py-1.5 text-right">{h.value != null ? usd(h.value) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {total > 0 && (
              <p className="text-muted text-xs mt-3">
                Total value in this file: {usd(total)}
              </p>
            )}

            <button
              onClick={onCommit}
              disabled={busy}
              className="mt-5 px-4 py-2 rounded-lg bg-accent text-black text-sm font-semibold disabled:opacity-50"
            >
              Import {preview.holdings.length} holdings
            </button>
          </>
        )}
      </Card>

      {preview.warnings.length > 0 && (
        <Card title="Warnings">
          <ul className="space-y-1.5 text-sm text-warning">
            {preview.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Card>
      )}

      {preview.skipped.length > 0 && (
        <Card title={`Skipped ${preview.skipped.length} rows`}>
          <ul className="space-y-1.5 text-sm">
            {preview.skipped.map((s) => (
              <li key={s.line} className="flex gap-3">
                <span className="text-muted text-xs w-10 shrink-0 pt-0.5">L{s.line}</span>
                <span className="flex-1">
                  <span className="text-muted truncate block max-w-lg">{s.raw}</span>
                  <span className="text-xs">{s.reason}</span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
