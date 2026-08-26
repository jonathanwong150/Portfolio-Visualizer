import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { NetWorthHistory } from "../api";
import { NetWorthChart } from "./NetWorthChart";

const TWO_POINTS: NetWorthHistory = {
  points: [
    { snapshot_at: "2024-01-01T12:00:00", net_worth: 100_000, num_holdings: 8 },
    { snapshot_at: "2024-02-01T12:00:00", net_worth: 142_000, num_holdings: 9 },
  ],
  prices_synthesized: false,
};

describe("NetWorthChart", () => {
  it("prompts for a sync when there are no snapshots at all", () => {
    render(<NetWorthChart history={{ points: [], prices_synthesized: false }} />);
    expect(screen.getByText(/no synced holdings yet/i)).toBeInTheDocument();
  });

  it("explains that one snapshot cannot make a line", () => {
    render(
      <NetWorthChart
        history={{
          points: [{ snapshot_at: "2024-01-01T12:00:00", net_worth: 100_000, num_holdings: 8 }],
          prices_synthesized: false,
        }}
      />,
    );
    expect(screen.getByText(/at least two syncs/i)).toBeInTheDocument();
  });

  it("reports the change between the first and last snapshot", () => {
    render(<NetWorthChart history={TWO_POINTS} />);
    // 142,000 - 100,000 = +42,000, which is +42.0% of 100,000.
    expect(screen.getByText(/\+\$42,000 \(42\.0%\)/)).toBeInTheDocument();
    // The latest value is the headline.
    expect(screen.getByText("$142,000")).toBeInTheDocument();
  });

  it("signs a decline negatively", () => {
    render(
      <NetWorthChart
        history={{
          points: [
            { snapshot_at: "2024-01-01T12:00:00", net_worth: 100_000, num_holdings: 8 },
            { snapshot_at: "2024-02-01T12:00:00", net_worth: 80_000, num_holdings: 8 },
          ],
          prices_synthesized: false,
        }}
      />,
    );
    expect(screen.getByText(/-\$20,000 \(-20\.0%\)/)).toBeInTheDocument();
  });

  it("captions the chart when prices are synthesized", () => {
    render(<NetWorthChart history={{ ...TWO_POINTS, prices_synthesized: true }} />);
    expect(screen.getByText(/prototype/i)).toBeInTheDocument();
  });

  it("stays silent about price provenance when prices are real", () => {
    render(<NetWorthChart history={TWO_POINTS} />);
    expect(screen.queryByText(/prototype/i)).not.toBeInTheDocument();
  });

  it("does not divide by zero when the first snapshot was worth nothing", () => {
    render(
      <NetWorthChart
        history={{
          points: [
            { snapshot_at: "2024-01-01T12:00:00", net_worth: 0, num_holdings: 0 },
            { snapshot_at: "2024-02-01T12:00:00", net_worth: 5_000, num_holdings: 1 },
          ],
          prices_synthesized: false,
        }}
      />,
    );
    // No baseline to compare against, so no percentage is claimed.
    expect(screen.getByText("+$5,000")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });
});
