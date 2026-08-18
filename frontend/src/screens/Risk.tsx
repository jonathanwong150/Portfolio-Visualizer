import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Card, Stat } from "../components/Card";
import { Heatmap } from "../components/Heatmap";
import { pct } from "../format";

export function Risk() {
  const risk = useQuery({ queryKey: ["risk"], queryFn: api.risk });
  const corr = useQuery({ queryKey: ["correlation"], queryFn: api.correlation });

  if (risk.isLoading || corr.isLoading) return <div className="text-muted">Loading…</div>;

  const r = risk.data;
  const fmt = (n: number | null | undefined, f: (x: number) => string) =>
    n == null ? "—" : f(n);

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <Stat label="Beta" value={fmt(r?.beta, (x) => x.toFixed(2))} sub="vs S&P 500" />
        </Card>
        <Card>
          <Stat
            label="Volatility"
            value={fmt(r?.annualized_volatility, (x) => pct(x))}
            sub="annualized"
          />
        </Card>
        <Card>
          <Stat label="Sharpe" value={fmt(r?.sharpe_ratio, (x) => x.toFixed(2))} sub="risk-adjusted" />
        </Card>
        <Card>
          <Stat
            label="Max Drawdown"
            value={fmt(r?.max_drawdown, (x) => pct(x))}
            sub="peak-to-trough"
          />
        </Card>
      </div>

      <Card title="Return Correlation (held positions)">
        <Heatmap
          labels={corr.data?.tickers ?? []}
          matrix={corr.data?.matrix ?? []}
          scale="diverging"
          format={(v) => v.toFixed(2)}
        />
        <div className="flex items-center gap-4 mt-4 text-xs text-muted">
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded" style={{ background: "rgb(246,70,93)" }} />
            −1 inverse
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded" style={{ background: "rgb(60,66,76)" }} />
            0
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded" style={{ background: "rgb(0,208,156)" }} />
            +1 aligned
          </span>
        </div>
      </Card>
    </div>
  );
}
