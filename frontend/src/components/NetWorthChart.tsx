import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { NetWorthHistory } from "../api";
import { CHART_COLORS, pct, usd } from "../format";

const ACCENT = CHART_COLORS[0];

const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });

export function NetWorthChart({ history }: { history: NetWorthHistory }) {
  const { points, prices_synthesized } = history;

  if (points.length === 0) {
    return (
      <p className="text-muted text-sm">
        No synced holdings yet — connect an account on the Accounts screen to start the history.
      </p>
    );
  }

  const first = points[0];
  const last = points[points.length - 1];
  const change = last.net_worth - first.net_worth;
  // A zero baseline has no meaningful percentage, so none is shown.
  const changePct = first.net_worth > 0 ? change / first.net_worth : null;

  const data = points.map((p) => ({
    label: shortDate(p.snapshot_at),
    net_worth: p.net_worth,
  }));

  return (
    <div>
      <div className="flex items-baseline gap-3 mb-3">
        <span className="text-2xl font-semibold">{usd(last.net_worth)}</span>
        <span className={change >= 0 ? "text-accent" : "text-danger"}>
          {change >= 0 ? "+" : "-"}
          {usd(Math.abs(change))}
          {changePct !== null && <> ({pct(changePct)})</>}
        </span>
      </div>

      {points.length < 2 ? (
        <p className="text-muted text-sm">
          A line needs at least two syncs — this is the only snapshot so far.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
            <CartesianGrid stroke="#ffffff10" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 12, fill: "#8b95a5" }} tickLine={false} />
            <YAxis
              tick={{ fontSize: 12, fill: "#8b95a5" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={usd}
              width={72}
            />
            <Tooltip
              formatter={(v: number) => [usd(v), "Net worth"]}
              contentStyle={{ background: "#1c232c", border: "none", borderRadius: 12 }}
            />
            <Area
              type="monotone"
              dataKey="net_worth"
              stroke={ACCENT}
              fill={ACCENT}
              fillOpacity={0.15}
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}

      {prices_synthesized && (
        <p className="text-muted text-xs mt-2">
          Prices are generated for the prototype, not observed market data.
        </p>
      )}
    </div>
  );
}
