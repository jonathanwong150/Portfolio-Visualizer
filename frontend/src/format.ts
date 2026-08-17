export const usd = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

export const pct = (n: number, digits = 1) => `${(n * 100).toFixed(digits)}%`;

// Palette used across charts (Robinhood/Coinbase-ish).
export const CHART_COLORS = [
  "#00d09c",
  "#3b82f6",
  "#a855f7",
  "#f59e0b",
  "#ef4444",
  "#14b8a6",
  "#ec4899",
  "#84cc16",
  "#f97316",
  "#6366f1",
];
