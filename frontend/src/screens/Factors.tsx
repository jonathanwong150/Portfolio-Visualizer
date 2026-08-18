import { useQuery } from "@tanstack/react-query";
import { api, FactorTilt } from "../api";
import { Card } from "../components/Card";
import { pct } from "../format";

export function Factors() {
  const factors = useQuery({ queryKey: ["factors"], queryFn: api.factors });

  if (factors.isLoading) return <div className="text-muted">Loading…</div>;
  if (factors.error) return <div className="text-danger">Failed to load factors.</div>;

  return (
    <div className="space-y-5">
      <Card title="Factor Tilts (value-weighted, look-through)">
        <div className="space-y-5">
          {(factors.data ?? []).map((f) => (
            <TiltBar key={f.factor} f={f} />
          ))}
        </div>
        <p className="text-xs text-muted mt-5">
          Rule-based approximation from fundamentals (P/E, P/B, ROE, momentum,
          market cap, beta). A production build measures true factor loadings via
          regression.
        </p>
      </Card>
    </div>
  );
}

function TiltBar({ f }: { f: FactorTilt }) {
  // score in [-1, 1]; render a center-anchored bar.
  const pctFromCenter = (f.score / 2) * 100; // -50%..50%
  const leaningHigh = f.score >= 0;

  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className={!leaningHigh ? "text-accent font-medium" : "text-muted"}>
          {f.low_label}
        </span>
        <span className="uppercase tracking-wide text-muted">{f.factor}</span>
        <span className={leaningHigh ? "text-accent font-medium" : "text-muted"}>
          {f.high_label}
        </span>
      </div>
      <div className="relative h-3 bg-surface2 rounded-full">
        {/* center line */}
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-white/20" />
        {/* fill */}
        <div
          className="absolute top-0 bottom-0 rounded-full bg-accent"
          style={
            leaningHigh
              ? { left: "50%", width: `${pctFromCenter}%` }
              : { right: "50%", width: `${-pctFromCenter}%` }
          }
        />
      </div>
      <div className="text-[11px] text-muted mt-1 text-center">
        {pct(f.high_weight, 0)} toward {f.high_label} · score {f.score.toFixed(2)}
      </div>
    </div>
  );
}
