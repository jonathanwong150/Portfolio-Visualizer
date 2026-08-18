import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Card } from "../components/Card";
import { Heatmap } from "../components/Heatmap";
import { pct } from "../format";

export function Overlap() {
  const overlap = useQuery({ queryKey: ["overlap"], queryFn: api.overlap });

  if (overlap.isLoading) return <div className="text-muted">Loading…</div>;
  if (overlap.error) return <div className="text-danger">Failed to load overlap.</div>;

  const data = overlap.data!;

  // Find the most-overlapping off-diagonal pair for a callout.
  let best = { a: "", b: "", v: 0 };
  for (let i = 0; i < data.etfs.length; i++) {
    for (let j = i + 1; j < data.etfs.length; j++) {
      if (data.matrix[i][j] > best.v) {
        best = { a: data.etfs[i], b: data.etfs[j], v: data.matrix[i][j] };
      }
    }
  }

  return (
    <div className="space-y-5">
      {best.v > 0 && (
        <Card>
          <div className="text-sm">
            <span className="text-muted">Highest overlap: </span>
            <span className="font-semibold">
              {best.a} ↔ {best.b}
            </span>{" "}
            share <span className="text-accent font-semibold">{pct(best.v)}</span> of
            holdings by weight.
          </div>
        </Card>
      )}

      <Card title="ETF Overlap (shared constituent weight)">
        {data.etfs.length > 1 ? (
          <Heatmap
            labels={data.etfs}
            matrix={data.matrix}
            scale="sequential"
            format={(v) => `${Math.round(v * 100)}%`}
          />
        ) : (
          <div className="text-muted text-sm">
            Need at least two ETFs to compute overlap.
          </div>
        )}
      </Card>
    </div>
  );
}
