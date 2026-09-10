import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type CompanyExposure } from "../api";
import { Card } from "../components/Card";
import { CHART_COLORS, pct, usd } from "../format";

export function Exposure() {
  const companies = useQuery({ queryKey: ["companies"], queryFn: api.companies });
  const sectors = useQuery({ queryKey: ["sectors"], queryFn: api.sectors });
  const [search, setSearch] = useState("");

  if (companies.isLoading) return <div className="text-muted">Loading…</div>;
  if (companies.error) {
    return <div className="text-danger">Failed to load company exposure.</div>;
  }

  const all = companies.data ?? [];
  const unresolved = all.filter((exposure) => exposure.is_unresolved);
  const unresolvedValue = unresolved.reduce((total, exposure) => total + exposure.value, 0);
  const unresolvedWeight = unresolved.reduce((total, exposure) => total + exposure.weight, 0);
  const named = all.filter((exposure) => !exposure.is_unresolved);
  const filtered = named.filter(
    (e) =>
      e.ticker.toLowerCase().includes(search.toLowerCase()) ||
      e.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-5">
      {/* Sector breakdown */}
      <Card title="Sector Exposure (look-through)">
        {sectors.isLoading ? (
          <p className="text-muted text-sm">Loading…</p>
        ) : sectors.error ? (
          <p className="text-danger text-sm">Failed to load sector exposure.</p>
        ) : (sectors.data?.length ?? 0) === 0 ? (
          <p className="text-muted text-sm">No sector exposure.</p>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={sectors.data} layout="vertical" margin={{ left: 40 }}>
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="label"
                width={130}
                tick={{ fill: "#8a94a6", fontSize: 12 }}
              />
              <Tooltip
                formatter={(v: number) => usd(v)}
                contentStyle={{ background: "#1c232c", border: "none", borderRadius: 12 }}
              />
              <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                {sectors.data!.map((_, i) => (
                  <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </Card>

      {unresolvedValue > 0 && (
        <Card title="Unresolved ETF Exposure">
          <div data-testid="unresolved-exposure">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-lg font-semibold">{pct(unresolvedWeight)} unresolved</span>
              <span className="font-semibold">{usd(unresolvedValue)}</span>
            </div>
            <p className="text-sm text-muted mt-1">
              Constituent data does not identify this part of the portfolio, so it is
              excluded from named company rankings.
            </p>
            <div className="mt-3 space-y-2">
              {unresolved.map((exposure) => (
                <div key={exposure.ticker} className="flex justify-between gap-3 text-sm">
                  <span>{exposure.name}</span>
                  <span className="text-muted">
                    {usd(exposure.value)} · {pct(exposure.weight)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* Searchable true-exposure list */}
      <Card title="True Company Exposure">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search e.g. NVDA…"
          className="w-full mb-4 bg-surface2 rounded-xl px-4 py-2 text-sm outline-none placeholder:text-muted"
        />
        <div className="space-y-1" data-testid="named-company-exposure">
          {filtered.map((e) => (
            <ExposureRow key={e.ticker} e={e} />
          ))}
          {filtered.length === 0 && (
            <div className="text-muted text-sm">No matches.</div>
          )}
        </div>
      </Card>
    </div>
  );
}

function ExposureRow({
  e,
}: {
  e: CompanyExposure;
}) {
  const directPct = e.value > 0 ? e.direct_value / e.value : 0;
  return (
    <div className="py-2 border-b border-white/5 last:border-0">
      <div className="flex items-center gap-3">
        <span className="font-semibold w-16">{e.ticker}</span>
        <span className="flex-1 text-muted text-sm truncate">{e.name}</span>
        <span className="font-semibold">{pct(e.weight)}</span>
        <span className="text-muted text-sm w-20 text-right">{usd(e.value)}</span>
      </div>
      {/* direct vs ETF split bar */}
      <div className="mt-1.5 flex h-1.5 rounded-full overflow-hidden bg-surface2 ml-16">
        <div className="bg-accent" style={{ width: `${directPct * 100}%` }} />
        <div className="bg-blue-500" style={{ width: `${(1 - directPct) * 100}%` }} />
      </div>
      {e.via_etf_value > 0 && (
        <div className="text-xs text-muted mt-1 ml-16">
          {usd(e.direct_value)} direct · {usd(e.via_etf_value)} via{" "}
          {e.source_etfs.join(", ")}
        </div>
      )}
    </div>
  );
}
