import { describe, expect, it } from "vitest";
import { CHART_COLORS, pct, usd } from "./format";

describe("usd", () => {
  it("formats to whole dollars with a thousands separator", () => {
    expect(usd(1234.56)).toBe("$1,235");
    expect(usd(1000000)).toBe("$1,000,000");
  });

  it("renders zero as a dollar amount, not a blank", () => {
    expect(usd(0)).toBe("$0");
  });

  it("keeps negatives signed", () => {
    expect(usd(-4200)).toBe("-$4,200");
  });
});

describe("pct", () => {
  it("scales a fraction to a percentage with one decimal", () => {
    expect(pct(0.1234)).toBe("12.3%");
    expect(pct(1)).toBe("100.0%");
    expect(pct(0)).toBe("0.0%");
  });

  it("honours a custom precision", () => {
    expect(pct(0.1234, 2)).toBe("12.34%");
    expect(pct(0.1234, 0)).toBe("12%");
  });

  it("keeps negative tilts signed", () => {
    expect(pct(-0.05)).toBe("-5.0%");
  });
});

describe("CHART_COLORS", () => {
  // Every chart indexes this with `i % CHART_COLORS.length`, so an empty
  // array would silently produce undefined fills.
  it("is non-empty and all hex values", () => {
    expect(CHART_COLORS.length).toBeGreaterThan(0);
    for (const c of CHART_COLORS) expect(c).toMatch(/^#[0-9a-f]{6}$/i);
  });
});
