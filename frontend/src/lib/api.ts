import type {
  AuditProgress,
  AuditWithHealth,
  FileContentResponse,
  FileTreeResponse,
  FixProposal,
  GitHubMetadata,
  KnowledgeBaseStats,
  ModelComparison,
  ModelInfo,
  RecurringFinding,
  RepositorySummary,
  RunComparison,
  RunListItem,
  TraceEvent,
} from "./types";

const BASE = "/api";

/** Default ceiling for a request. `fetch` has no timeout of its own, so
 *  without this a stalled backend leaves the UI on a spinner indefinitely
 *  with no way for the user to tell a slow response from a dead one. */
const DEFAULT_TIMEOUT_MS = 30_000;
/** Endpoints that legitimately take longer because they call a model
 *  provider. Kept comfortably above the backend's own budget for the same
 *  work, so the server's clear error message wins the race against the
 *  client's generic one. */
const LONG_TIMEOUT_MS = 120_000;

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Distinguished from ApiError so the UI can say "this timed out" rather
 *  than reporting a misleading HTTP failure. */
class ApiTimeoutError extends Error {
  // Declared and assigned explicitly rather than via a parameter property,
  // which `erasableSyntaxOnly` disallows.
  readonly timeoutMs: number;
  constructor(timeoutMs: number) {
    super(
      `The server did not respond within ${Math.round(timeoutMs / 1000)}s. ` +
        `It may be busy or a model provider may be unavailable — try again.`,
    );
    this.name = "ApiTimeoutError";
    this.timeoutMs = timeoutMs;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      ...init,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiTimeoutError(timeoutMs);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* body wasn't JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // Trimmed here so every caller benefits. A pasted URL with a leading
  // space was treated as a local filesystem path by the backend and failed
  // with "Repo path does not exist: <the URL>" — which reads as nonsense,
  // because HTML collapses leading whitespace and the error banner showed a
  // perfectly valid-looking URL.
  startAudit: (source: string) =>
    request<{ run_id: string; status: string }>("/audits", {
      method: "POST",
      body: JSON.stringify({ source: source.trim() }),
    }),

  listAudits: (repoId?: string) =>
    request<RunListItem[]>(repoId ? `/audits?repo_id=${encodeURIComponent(repoId)}` : "/audits"),

  listRepositories: () => request<{ repositories: RepositorySummary[] }>("/audits/repositories"),

  recurringFindings: (repoId: string, minRuns = 2) =>
    request<{ repo_id: string; min_runs: number; findings: RecurringFinding[] }>(
      `/audits/recurring?repo_id=${encodeURIComponent(repoId)}&min_runs=${minRuns}`,
    ),

  knowledgeBase: (repoId?: string) =>
    request<KnowledgeBaseStats>(
      repoId ? `/memory/knowledge-base?repo_id=${encodeURIComponent(repoId)}` : "/memory/knowledge-base",
    ),

  searchKnowledgeBase: (repoId: string, q: string, topK = 8) =>
    request<{
      repo_id: string;
      query: string;
      hybrid: boolean;
      results: { file: string; start_line: number; score: number; semantic_score: number; text: string }[];
    }>(`/memory/search?repo_id=${encodeURIComponent(repoId)}&q=${encodeURIComponent(q)}&top_k=${topK}`),

  getAuditStatus: (runId: string) => request<AuditProgress>(`/audits/${runId}/status`),

  getAuditEvents: (runId: string) => request<{ run_id: string; events: TraceEvent[] }>(`/audits/${runId}/events`),

  getAudit: (runId: string) => request<AuditWithHealth>(`/audits/${runId}`),

  compareRuns: (runA: string, runB: string) =>
    request<RunComparison>(`/audits/compare?run_a=${encodeURIComponent(runA)}&run_b=${encodeURIComponent(runB)}`),

  // Both of these call live model providers, so they get the long ceiling.
  proposeFixes: (runId: string, opts: { max_findings?: number; fingerprints?: string[] }) =>
    request<FixProposal[]>(
      `/audits/${runId}/fixes`,
      { method: "POST", body: JSON.stringify(opts) },
      LONG_TIMEOUT_MS,
    ),

  compareModels: (prompt: string, providers?: string[]) =>
    request<ModelComparison>(
      "/models/compare",
      { method: "POST", body: JSON.stringify({ prompt, providers }) },
      LONG_TIMEOUT_MS,
    ),

  getFileTree: (runId: string) => request<FileTreeResponse>(`/audits/${runId}/files`),

  getFileContent: (runId: string, path: string) =>
    request<FileContentResponse>(`/audits/${runId}/file?path=${encodeURIComponent(path)}`),

  getRepositoryMetadata: (source: string) =>
    request<GitHubMetadata>(`/repository/metadata?source=${encodeURIComponent(source)}`),

  availableModels: () => request<{ providers: ModelInfo[] }>("/models/available"),

  reportUrl: (runId: string, format: "md" | "html" | "json" | "pdf") => `${BASE}/audits/${runId}/report.${format}`,
};

export { ApiError, ApiTimeoutError, DEFAULT_TIMEOUT_MS, LONG_TIMEOUT_MS };
