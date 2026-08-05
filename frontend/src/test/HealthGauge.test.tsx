import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HealthGauge, CategoryBar } from "../components/HealthGauge";

describe("HealthGauge", () => {
  it("renders the numeric score", () => {
    render(<HealthGauge score={72} />);
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("Health")).toBeInTheDocument();
  });

  it("renders 0 and 100 edge cases without crashing", () => {
    const { rerender } = render(<HealthGauge score={0} />);
    expect(screen.getByText("0")).toBeInTheDocument();
    rerender(<HealthGauge score={100} />);
    expect(screen.getByText("100")).toBeInTheDocument();
  });
});

describe("CategoryBar", () => {
  it("renders the label and score", () => {
    render(<CategoryBar label="Security" score={56} />);
    expect(screen.getByText("Security")).toBeInTheDocument();
    expect(screen.getByText("56")).toBeInTheDocument();
  });
});
