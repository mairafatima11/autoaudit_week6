import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./test-utils";
import { Dashboard } from "../pages/Dashboard";
import type { AuditWithHealth, Finding, RunListItem } from "../lib/types";

const RUN_ID = "run_test_1";

function finding(over: Partial<Finding>): Finding {
  return {
    fingerprint: Math.random().toString(36).slice(2),
    file: "src/a.py",
    line: 1,
    category: "quality",
    rule: "long-function",
    title: "Long function",
    description: "d",
    severity: "low",
    source_agent: "quality",
    source_tool: "heuristic",
    status: "new",
    confidence: 0.5,
    ...over,
  };
}

const audit: AuditWithHealth = {
  report: {
    run_id: RUN_ID,
    repo_id: "repo1",
    repo_source: "/tmp/repo",
    timestamp: 1,
    findings: [
      finding({ severity: "high", status: "new" }),
      finding({ severity: "medium", status: "recurring" }),
      // Two issues resolved since the previous run — they must NOT be
      // counted as current problems in the severity tiles.
      finding({ severity: "high", status: "fixed" }),
      finding({ severity: "high", status: "fixed" }),
    ],
    files_scanned: 42,
    chunks_indexed: 100,
    is_first_run: false,
    doc_suggestions: [],
    reconciled_findings: [],
    architecture_explanation: "",
    repo_profile: {
      total_files: 42, total_directories: 5, package_manager: "pip",
      frameworks: [], languages: {}, primary_language: "python",
    },
    test_coverage: {
      measured: true, score: 64, source_files: 10, test_files: 4,
      test_cases: 22, source_symbols: 30, modules_with_tests: 6,
      module_coverage_pct: 60,
    },
    degraded_suggestions: 0,
  },
  health_score: {
    overall: 71, security: 55, quality: 80, documentation: 66,
    architecture: 74, test_coverage: 64, technical_debt: 70,
    test_coverage_measured: true,
  },
};

const runs: RunListItem[] = [
  {
    run_id: RUN_ID, repo_id: "repo1", repo_source: "/tmp/repo", ts: 1, status: "done",
    health_score: audit.health_score, files_scanned: 42, chunks_indexed: 100,
    finding_count: 4, severity_counts: { high: 3, medium: 1, low: 0, info: 0 },
  },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const routes: Record<string, unknown> = {
        "/api/audits": runs,
        [`/api/audits/${RUN_ID}`]: audit,
        [`/api/audits/${RUN_ID}/status`]: {
          run_id: RUN_ID, status: "done", percent: 100, stages: [], error: null,
        },
        "/api/memory/knowledge-base": {
          repo_id: "repo1", embedding_dim: 256, total_chunks: 1234,
          indexed_repositories: 1, per_repo: [], top_files: [],
        },
        "/api/models/available": {
          providers: [{ id: "gemini", model: "gemini-2.5-flash", live: true }],
        },
        ...overrides,
      };
      const path = url.split("?")[0];
      const body = routes[path] ?? routes[url] ?? {};
      return { ok: true, status: 200, json: async () => body };
    }),
  );
}

describe("Dashboard health score display", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("autoaudit:active-run-id", RUN_ID);
    stubFetch();
  });

  it("renders every scored category, including test coverage", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => expect(screen.getByText("Security")).toBeInTheDocument());

    for (const label of ["Security", "Quality", "Documentation", "Architecture", "Technical debt"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    // Test coverage carries 10% of the composite but was previously computed
    // and never rendered, so the bars couldn't explain the overall number.
    expect(screen.getByText("Test coverage")).toBeInTheDocument();
  });

  it("shows what the test-coverage heuristic actually measured", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => expect(screen.getByText("Test coverage")).toBeInTheDocument());
    expect(screen.getByText(/6\/10 modules covered/)).toBeInTheDocument();
    expect(screen.getByText(/22 test cases/)).toBeInTheDocument();
  });

  it("excludes findings fixed since the last run from the severity tiles", async () => {
    renderWithProviders(<Dashboard />);
    // 3 high-severity findings exist in the report, but 2 are `fixed` — only
    // 1 is a current problem. Counting all of them meant the tile could rise
    // after the user fixed something.
    await waitFor(() =>
      expect(screen.getByText("2 fixed since the previous run")).toBeInTheDocument(),
    );
    // StatCard renders <label> then <value> as sibling <p>s inside one card.
    const highCard = screen.getByText("High").closest("div")?.parentElement;
    expect(highCard?.textContent).toBe("High1");
  });

  it("reports test coverage as not measured rather than showing a zero", async () => {
    stubFetch({
      [`/api/audits/${RUN_ID}`]: {
        ...audit,
        health_score: { ...audit.health_score, test_coverage: 0, test_coverage_measured: false },
      },
    });
    renderWithProviders(<Dashboard />);
    await waitFor(() => expect(screen.getByText("not measured")).toBeInTheDocument());
  });

  it("stays quiet when nothing was degraded", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => expect(screen.getByText("Security")).toBeInTheDocument());
    expect(screen.queryByText(/could not be generated/)).not.toBeInTheDocument();
  });

  it("warns when a provider outage left placeholder descriptions", async () => {
    // Otherwise the user reads "[not drafted...]" as if it were model output.
    stubFetch({
      [`/api/audits/${RUN_ID}`]: {
        ...audit,
        report: { ...audit.report, degraded_suggestions: 12 },
      },
    });
    renderWithProviders(<Dashboard />);
    await waitFor(() =>
      expect(screen.getByText("Some descriptions could not be generated")).toBeInTheDocument(),
    );
    expect(screen.getByText(/12 items kept a heuristic description/)).toBeInTheDocument();
    expect(screen.getByText(/Detection, severities and evidence are unaffected/)).toBeInTheDocument();
  });

  it("surfaces memory and model status", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => expect(screen.getByText("1234")).toBeInTheDocument());
    expect(screen.getByText("Chunks indexed")).toBeInTheDocument();
    expect(screen.getByText("256")).toBeInTheDocument();
    expect(screen.getByText("live")).toBeInTheDocument();
  });
});
