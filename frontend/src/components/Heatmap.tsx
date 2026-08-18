// Lightweight CSS-grid heatmap. Used for ETF overlap and return correlation.
import { Fragment } from "react";

function lerp(a: number, b: number, t: number) {
  return Math.round(a + (b - a) * t);
}

/**
 * Map a value to a background color.
 * - "diverging" (correlation, -1..1): red (neg) -> gray (0) -> green (pos)
 * - "sequential" (overlap, 0..max):   dark -> accent green
 */
function colorFor(
  value: number,
  scale: "diverging" | "sequential",
  max = 1
): string {
  if (scale === "diverging") {
    const t = Math.max(-1, Math.min(1, value));
    if (t >= 0) {
      // gray -> green
      const r = lerp(60, 0, t);
      const g = lerp(66, 208, t);
      const b = lerp(76, 156, t);
      return `rgb(${r},${g},${b})`;
    }
    // gray -> red
    const k = -t;
    const r = lerp(60, 246, k);
    const g = lerp(66, 70, k);
    const b = lerp(76, 93, k);
    return `rgb(${r},${g},${b})`;
  }
  // sequential
  const t = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const r = lerp(28, 0, t);
  const g = lerp(35, 208, t);
  const b = lerp(44, 156, t);
  return `rgb(${r},${g},${b})`;
}

export function Heatmap({
  labels,
  matrix,
  scale = "diverging",
  format = (v) => v.toFixed(2),
}: {
  labels: string[];
  matrix: number[][];
  scale?: "diverging" | "sequential";
  format?: (v: number) => string;
}) {
  if (!labels.length || !matrix.length) {
    return <div className="text-muted text-sm">Not enough data.</div>;
  }
  const max = Math.max(...matrix.flat());
  const n = labels.length;

  return (
    <div className="overflow-x-auto">
      <div
        className="grid gap-1 min-w-fit"
        style={{ gridTemplateColumns: `48px repeat(${n}, minmax(40px, 1fr))` }}
      >
        {/* header row */}
        <div />
        {labels.map((l) => (
          <div key={`h-${l}`} className="text-[10px] text-muted text-center truncate">
            {l}
          </div>
        ))}
        {/* body rows */}
        {matrix.map((row, i) => (
          <Fragment key={`row-${labels[i]}`}>
            <div className="text-[10px] text-muted flex items-center justify-end pr-1 truncate">
              {labels[i]}
            </div>
            {row.map((v, j) => (
              <div
                key={`c-${i}-${j}`}
                title={`${labels[i]} · ${labels[j]}: ${format(v)}`}
                className="aspect-square rounded flex items-center justify-center text-[9px] font-medium text-white/90"
                style={{ background: colorFor(v, scale, max) }}
              >
                {n <= 8 ? format(v) : ""}
              </div>
            ))}
          </Fragment>
        ))}
      </div>
    </div>
  );
}
