import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Card, Stat } from "./Card";

describe("Card", () => {
  it("renders its title as a heading alongside the children", () => {
    render(
      <Card title="Allocation by Account">
        <p>body</p>
      </Card>,
    );
    expect(screen.getByRole("heading", { name: "Allocation by Account" })).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("omits the heading entirely when untitled", () => {
    render(
      <Card>
        <p>body</p>
      </Card>,
    );
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("appends a caller-supplied className to its own", () => {
    const { container } = render(<Card className="col-span-2">body</Card>);
    expect(container.firstElementChild).toHaveClass("col-span-2");
    expect(container.firstElementChild).toHaveClass("bg-surface");
  });
});

describe("Stat", () => {
  it("renders the label, value and sub-line", () => {
    render(<Stat label="Net Worth" value="$142,000" sub="+$12,000 unrealized" />);
    expect(screen.getByText("Net Worth")).toBeInTheDocument();
    expect(screen.getByText("$142,000")).toBeInTheDocument();
    expect(screen.getByText("+$12,000 unrealized")).toBeInTheDocument();
  });

  it("renders nothing for sub when it is absent", () => {
    const { container } = render(<Stat label="Accounts" value="3" />);
    // label + value only — a stray empty sub div would make this 3.
    expect(container.firstElementChild!.childElementCount).toBe(2);
  });
});
