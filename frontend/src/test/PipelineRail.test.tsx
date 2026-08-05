import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PipelineRail } from "../components/PipelineRail";
import type { PipelineStage } from "../lib/types";

describe("PipelineRail", () => {
  it("renders default stage labels when no stages are passed", () => {
    render(<PipelineRail />);
    expect(screen.getByText("Supervisor")).toBeInTheDocument();
    expect(screen.getByText("Security")).toBeInTheDocument();
    expect(screen.getByText("Report")).toBeInTheDocument();
  });

  it("renders custom stages with correct labels", () => {
    const stages: PipelineStage[] = [
      { agent: "supervisor", status: "completed", duration_seconds: 1.2, current_file: null },
      { agent: "security_agent", status: "running", duration_seconds: 2.5, current_file: "src/app.py" },
      { agent: "quality_agent", status: "pending", duration_seconds: null, current_file: null },
    ];
    render(<PipelineRail stages={stages} />);
    expect(screen.getByText("Supervisor")).toBeInTheDocument();
    expect(screen.getByText("Security")).toBeInTheDocument();
    expect(screen.getByText("Quality")).toBeInTheDocument();
  });

  it("renders an unrecognized agent name verbatim", () => {
    const stages: PipelineStage[] = [{ agent: "mystery_agent", status: "pending", duration_seconds: null, current_file: null }];
    render(<PipelineRail stages={stages} />);
    expect(screen.getByText("mystery_agent")).toBeInTheDocument();
  });

  it("hides labels when showLabels is false", () => {
    const stages: PipelineStage[] = [{ agent: "supervisor", status: "completed", duration_seconds: 1.2, current_file: null }];
    render(<PipelineRail stages={stages} showLabels={false} />);
    expect(screen.queryByText("Supervisor")).not.toBeInTheDocument();
  });
});
