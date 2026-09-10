import { useQuery } from "@tanstack/react-query";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { api, exportUrls } from "../api";
import { Card, Stat } from "../components/Card";
import { NetWorthChart } from "../components/NetWorthChart";
import { CHART_COLORS, pct, usd } from "../format";

export function Dashboard() {
  const summary = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  const companies = useQuery({ queryKey: ["companies"], queryFn: api.companies });
  const risk = useQuery({ queryKey: ["risk"], queryFn: api.risk });
  const history = useQuery({ queryKey: ["history"], queryFn: api.history });

  if (summary.isLoading || companies.isLoading) {
    return <div className="text-muted">Loading…</div>;
  }
  if (summary.error) return <div className="text-danger">Failed to load summary.</div>;
  if (companies.error) return <div className="text-danger">Failed to load exposure.</div>;

  const s = summary.data!;
  const exposures = companies.data ?? [];
  const unresolved = exposures.filter((exposure) => exposure.is_unresolved);
  const unresolvedValue = unresolved.reduce((total, exposure) => total + exposure.value, 0);
  const unresolvedWeight = unresolved.reduce((total, exposure) => total + exposure.weight, 0);
  const top = exposures.filter((exposure) => !exposure.is_unresolved).slice(0, 10);
  const gain = s.net_worth - s.total_invested;

  return (
    <div className="space-y-5">
      {/* Top stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <Stat label="Net Worth" value={usd(s.net_worth)} />
        </Card>
        <Card>
          <Stat
            label="Total Invested"
            value={usd(s.total_invested)}
            sub={`${gain >= 0 ? "+" : ""}${usd(gain)} unrealized`}
          />
        </Card>
        <Card>
          <Stat label="Accounts" value={String(s.num_accounts)} sub={`${s.num_holdings} positions`} />
        </Card>
        <Card>
          <Stat
            label="Portfolio Beta"
            value={risk.data?.beta != null ? risk.data.beta.toFixed(2) : "—"}
            sub={risk.data?.annualized_volatility != null ? `${pct(risk.data.annualized_volatility)} vol` : undefined}
          />
        </Card>
      </div>

      {/* Net worth over time — one point per holdings snapshot */}
      <Card title="Net Worth Over Time">
        {history.error ? (
          <p className="text-danger text-sm">Failed to load history.</p>
        ) : history.data ? (
          <NetWorthChart history={history.data} />
        ) : (
          <p className="text-muted text-sm">Loading…</p>
        )}
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {/* Allocation by account */}
        <Card title="Allocation by Account">
          <AllocationDonut data={s.allocation_by_account} />
        </Card>

        {/* Top true exposures */}
        <Card title="Top Named Company Exposures (look-through)">
          {top.length === 0 ? (
            <p className="text-sm text-muted">No named company exposure yet.</p>
          ) : (
            <ul className="space-y-2">
              {top.map((e, i) => (
              <li key={`${e.is_unresolved ? "unresolved" : "named"}:${e.ticker}`} className="flex items-center gap-3">
                <span
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ background: CHART_COLORS[i % CHART_COLORS.length] }}
                />
                <span className="font-medium w-16">{e.ticker}</span>
                <span className="flex-1 text-muted text-sm truncate">{e.name}</span>
                <span className="font-semibold">{pct(e.weight)}</span>
              </li>
              ))}
            </ul>
          )}
          {unresolvedValue > 0 && (
            <div className="mt-4 pt-3 border-t border-white/10 text-sm">
              <div className="flex justify-between gap-3 font-medium">
                <span>{pct(unresolvedWeight)} unresolved</span>
                <span>{usd(unresolvedValue)}</span>
              </div>
              <p className="text-xs text-muted mt-1">
                {usd(unresolvedValue)} not attributed to named companies
              </p>
            </div>
          )}
        </Card>
      </div>

      <Card title="Export">
        <div className="flex flex-wrap gap-3">
          <DownloadLink href={exportUrls.holdings} label="Holdings CSV" />
          <DownloadLink href={exportUrls.exposure} label="Exposure CSV" />
        </div>
      </Card>
    </div>
  );
}

function DownloadLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      download
      className="px-4 py-2 rounded-lg bg-accent/10 text-accent text-sm font-medium hover:bg-accent/20 transition"
    >
      ↓ {label}
    </a>
  );
}

function AllocationDonut({ data }: { data: { label: string; value: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="label"
          innerRadius={60}
          outerRadius={100}
          paddingAngle={2}
        >
          {data.map((_, i) => (
            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          formatter={(v: number, n) => [usd(v), n as string]}
          contentStyle={{ background: "#1c232c", border: "none", borderRadius: 12 }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
