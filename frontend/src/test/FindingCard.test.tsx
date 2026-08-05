import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FindingCard, SeverityBadge, StatusPill } from "../components/FindingCard";
import type { Finding } from "../lib/types";

const baseFinding: Finding = {
  fingerprint: "abc123",
  file: "src/app.py",
  line: 42,
  category: "security",
  rule: "hardcoded-secret",
  title: "Possible hardcoded secret",
  description: "A secret-looking string was found.",
  evidence: "API_KEY = 'sk-live-...'",
  severity: "high",
  source_agent: "security",
  source_tool: "fallback-scanner",
  status: "new",
  confidence: 0.85,
};

describe("SeverityBadge", () => {
  it("renders the correct label for each severity", () => {
    (["high", "medium", "low", "info"] as const).forEach((sev) => {
      const { unmount } = render(<SeverityBadge severity={sev} />);
      expect(screen.getByText(new RegExp(sev, "i"))).toBeInTheDocument();
      unmount();
    });
  });
});

describe("StatusPill", () => {
  it("renders New / Recurring / Fixed correctly", () => {
    const { rerender } = render(<StatusPill status="new" />);
    expect(screen.getByText("New")).toBeInTheDocument();

    rerender(<StatusPill status="recurring" />);
    expect(screen.getByText("Recurring")).toBeInTheDocument();

    rerender(<StatusPill status="fixed" />);
    expect(screen.getByText("Fixed")).toBeInTheDocument();
  });
});

describe("FindingCard", () => {
  it("renders finding title, file:line, and rule", () => {
    render(<FindingCard finding={baseFinding} />);
    expect(screen.getByText("Possible hardcoded secret")).toBeInTheDocument();
    expect(screen.getByText(/src\/app\.py:42/)).toBeInTheDocument();
    expect(screen.getByText(/hardcoded-secret/)).toBeInTheDocument();
  });

  it("calls onSelect with the finding when clicked", () => {
    const onSelect = vi.fn();
    render(<FindingCard finding={baseFinding} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("Possible hardcoded secret"));
    expect(onSelect).toHaveBeenCalledWith(baseFinding);
  });

  it("shows the source agent", () => {
    render(<FindingCard finding={baseFinding} />);
    expect(screen.getByText("security")).toBeInTheDocument();
  });
});
