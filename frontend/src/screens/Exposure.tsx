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
import { api } from "../api";
import { Card } from "../components/Card";
import { CHART_COLORS, pct, usd } from "../format";

export function Exposure() {
  const companies = useQuery({ queryKey: ["companies"], queryFn: api.companies });
  const sectors = useQuery({ queryKey: ["sectors"], queryFn: api.sectors });
  const [search, setSearch] = useState("");

  if (companies.isLoading) return <div className="text-muted">Loading…</div>;

  const all = companies.data ?? [];
  const filtered = all.filter(
    (e) =>
      e.ticker.toLowerCase().includes(search.toLowerCase()) ||
      e.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-5">
      {/* Sector breakdown */}
      <Card title="Sector Exposure (look-through)">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={sectors.data ?? []} layout="vertical" margin={{ left: 40 }}>
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
              {(sectors.data ?? []).map((_, i) => (
                <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {/* Searchable true-exposure list */}
      <Card title="True Company Exposure">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search e.g. NVDA…"
          className="w-full mb-4 bg-surface2 rounded-xl px-4 py-2 text-sm outline-none placeholder:text-muted"
        />
        <div className="space-y-1">
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
  e: {
    ticker: string;
    name: string;
    value: number;
    weight: number;
    direct_value: number;
    via_etf_value: number;
    source_etfs: string[];
  };
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
