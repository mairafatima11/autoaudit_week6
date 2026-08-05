import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./test-utils";
import { MemoryPage } from "../pages/MemoryPage";
import type { RepoHealthScore, RunListItem } from "../lib/types";

function health(overall: number): RepoHealthScore {
  return {
    overall, security: 80, quality: 70, documentation: 60,
    architecture: 75, test_coverage: 50, technical_debt: 65,
    test_coverage_measured: true,
  };
}

const repoARuns: RunListItem[] = [
  {
    run_id: "run_a2", repo_id: "repo-a", repo_source: "https://github.com/x/alpha",
    ts: 2000, status: "done", health_score: health(80), files_scanned: 50,
    chunks_indexed: 500, finding_count: 2,
    severity_counts: { high: 1, medium: 1, low: 0, info: 0 },
  },
  {
    run_id: "run_a1", repo_id: "repo-a", repo_source: "https://github.com/x/alpha",
    ts: 1000, status: "done", health_score: health(60), files_scanned: 50,
    chunks_indexed: 480, finding_count: 5,
    severity_counts: { high: 3, medium: 2, low: 0, info: 0 },
  },
];

const repoBRuns: RunListItem[] = [
  {
    run_id: "run_b1", repo_id: "repo-b", repo_source: "https://github.com/x/beta",
    ts: 1500, status: "done", health_score: health(30), files_scanned: 3,
    chunks_indexed: 9, finding_count: 1,
    severity_counts: { high: 0, medium: 0, low: 1, info: 0 },
  },
];

let requestedUrls: string[] = [];

function stubFetch() {
  requestedUrls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      requestedUrls.push(url);
      const [path, qs = ""] = url.split("?");
      const params = new URLSearchParams(qs);
      let body: unknown = {};

      if (path === "/api/audits/repositories") {
        body = {
          repositories: [
            { repo_id: "repo-a", repo_source: "https://github.com/x/alpha", run_count: 2, first_run_ts: 1000, last_run_ts: 2000 },
            { repo_id: "repo-b", repo_source: "https://github.com/x/beta", run_count: 1, first_run_ts: 1500, last_run_ts: 1500 },
          ],
        };
      } else if (path === "/api/audits") {
        body = params.get("repo_id") === "repo-b" ? repoBRuns : repoARuns;
      } else if (path === "/api/audits/recurring") {
        body = {
          repo_id: params.get("repo_id"), min_runs: 2,
          findings: [{
            fingerprint: "fp1", run_count: 4, file: "src/legacy.py", line: 12,
            category: "quality", rule: "long-function", title: "Long function (80 lines)",
            severity: "low", last_seen_ts: 2000,
          }],
        };
      } else if (path === "/api/memory/knowledge-base") {
        body = {
          repo_id: params.get("repo_id"), embedding_dim: 256, total_chunks: 500,
          indexed_repositories: 1, per_repo: [],
          top_files: [{ file: "src/legacy.py", chunks: 40, characters: 900 }],
        };
      }
      return { ok: true, status: 200, json: async () => body };
    }),
  );
}

describe("MemoryPage", () => {
  beforeEach(() => {
    localStorage.clear();
    stubFetch();
  });

  it("scopes history to one repository instead of mixing every repo into one trend", async () => {
    renderWithProviders(<MemoryPage />);
    await waitFor(() => expect(screen.getByText(/Showing 2 runs for/)).toBeInTheDocument());

    // The run list must be requested with an explicit repo filter — charting
    // runs from different repositories on one line is what made the old
    // "trend" meaningless.
    expect(requestedUrls.some((u) => u.startsWith("/api/audits?repo_id=repo-a"))).toBe(true);
    expect(screen.getByText("https://github.com/x/alpha")).toBeInTheDocument();
  });

  it("does not fan out one audit request per run", async () => {
    renderWithProviders(<MemoryPage />);
    await waitFor(() => expect(screen.getByText(/Showing 2 runs for/)).toBeInTheDocument());

    // Everything the timeline needs now comes back on the list response.
    const perRunFetches = requestedUrls.filter((u) => /^\/api\/audits\/run_/.test(u));
    expect(perRunFetches).toHaveLength(0);
  });

  it("renders the knowledge base stats the page is specified to show", async () => {
    renderWithProviders(<MemoryPage />);
    // Wait on the resolved values, not the static labels: the labels render
    // as soon as the query stops loading, which can be a tick before `data`
    // is populated.
    await waitFor(() => expect(screen.getByText("256")).toBeInTheDocument());
    expect(screen.getByText("Chunks indexed")).toBeInTheDocument();
    expect(screen.getByText("Embedding dimensions")).toBeInTheDocument();
    expect(screen.getByText("src/legacy.py")).toBeInTheDocument();
  });

  it("lists recurring findings with how many runs they appeared in", async () => {
    renderWithProviders(<MemoryPage />);
    await waitFor(() => expect(screen.getByText("Long function (80 lines)")).toBeInTheDocument());
    expect(screen.getByText("4 runs")).toBeInTheDocument();
  });

  it("shows real per-run health and chunk counts on the timeline", async () => {
    renderWithProviders(<MemoryPage />);
    await waitFor(() => expect(screen.getByText("80 health")).toBeInTheDocument());
    expect(screen.getByText("60 health")).toBeInTheDocument();
    expect(screen.getByText("500 chunks")).toBeInTheDocument();
  });

  it("shows an empty state when nothing has been audited", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ repositories: [] }) })),
    );
    renderWithProviders(<MemoryPage />);
    await waitFor(() => expect(screen.getByText("No history yet")).toBeInTheDocument());
  });
});
