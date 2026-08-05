import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./test-utils";
import { FindingsPage } from "../pages/FindingsPage";
import type { Finding } from "../lib/types";

const findings: Finding[] = [
  {
    fingerprint: "f1",
    file: "src/app.py",
    line: 3,
    category: "security",
    rule: "hardcoded-secret",
    title: "Possible hardcoded secret",
    description: "desc",
    evidence: "",
    severity: "high",
    source_agent: "security",
    source_tool: "fallback-scanner",
    status: "new",
    confidence: 0.9,
  },
  {
    fingerprint: "f2",
    file: "src/utils.py",
    line: 10,
    category: "quality",
    rule: "long-function",
    title: "Long function",
    description: "desc",
    evidence: "",
    severity: "low",
    source_agent: "quality",
    source_tool: "heuristic",
    status: "recurring",
    confidence: 0.4,
  },
];

function mockAuditFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/audits/run_1") && !url.includes("status") && !url.includes("events")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            report: {
              run_id: "run_1",
              repo_id: "r",
              repo_source: "tests/fixtures/mock_repo",
              timestamp: 0,
              findings,
              files_scanned: 2,
              chunks_indexed: 4,
              is_first_run: true,
              doc_suggestions: [],
              reconciled_findings: [],
            },
            health_score: { overall: 70, security: 60, quality: 90, documentation: 80, architecture: 85, test_coverage: 70, technical_debt: 85 },
          }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => [] });
    })
  );
}

describe("Findings page filters", () => {
  beforeEach(() => {
    localStorage.setItem("autoaudit:active-run-id", "run_1");
    mockAuditFetch();
  });

  it("shows all findings by default", async () => {
    renderWithProviders(<FindingsPage />);
    await waitFor(() => expect(screen.getByText("Possible hardcoded secret")).toBeInTheDocument());
    expect(screen.getByText("Long function")).toBeInTheDocument();
  });

  it("filters by severity", async () => {
    renderWithProviders(<FindingsPage />);
    await waitFor(() => expect(screen.getByText("Possible hardcoded secret")).toBeInTheDocument());

    fireEvent.click(screen.getByText("high"));

    expect(screen.getByText("Possible hardcoded secret")).toBeInTheDocument();
    expect(screen.queryByText("Long function")).not.toBeInTheDocument();
  });

  it("filters by free-text search", async () => {
    renderWithProviders(<FindingsPage />);
    await waitFor(() => expect(screen.getByText("Possible hardcoded secret")).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("Search findings…"), { target: { value: "long function" } });

    expect(screen.queryByText("Possible hardcoded secret")).not.toBeInTheDocument();
    expect(screen.getByText("Long function")).toBeInTheDocument();
  });

  it("opens advanced filters and filters by minimum confidence", async () => {
    renderWithProviders(<FindingsPage />);
    await waitFor(() => expect(screen.getByText("Possible hardcoded secret")).toBeInTheDocument());

    fireEvent.click(screen.getByText("More filters"));
    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: "0.5" } });

    // Only the high-confidence (0.9) finding should remain — the 0.4 one is filtered out.
    expect(screen.getByText("Possible hardcoded secret")).toBeInTheDocument();
    expect(screen.queryByText("Long function")).not.toBeInTheDocument();
  });

  it("filters by finding type (category)", async () => {
    renderWithProviders(<FindingsPage />);
    await waitFor(() => expect(screen.getByText("Possible hardcoded secret")).toBeInTheDocument());

    fireEvent.click(screen.getByText("More filters"));
    fireEvent.change(screen.getByDisplayValue("All types"), { target: { value: "quality" } });

    expect(screen.queryByText("Possible hardcoded secret")).not.toBeInTheDocument();
    expect(screen.getByText("Long function")).toBeInTheDocument();
  });

  it("shows an empty message when no findings match the filters", async () => {
    renderWithProviders(<FindingsPage />);
    await waitFor(() => expect(screen.getByText("Possible hardcoded secret")).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("Search findings…"), { target: { value: "nonexistent-xyz" } });

    expect(screen.getByText("No findings match your filters.")).toBeInTheDocument();
  });
});
