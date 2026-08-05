export type Severity = "high" | "medium" | "low" | "info";
// Must match the backend `Category` enum (autoaudit/schemas.py). This
// previously listed "documentation" and "architecture", neither of which any
// agent ever emits, so those Findings-page filter options always returned
// zero results while real `docs` findings had no filter at all.
export type FindingCategory = "security" | "quality" | "docs";
export type FindingStatus = "new" | "recurring" | "fixed";

export interface Finding {
  fingerprint: string;
  file: string;
  line: number;
  category: FindingCategory;
  rule: string;
  title: string;
  description: string;
  evidence?: string;
  severity: Severity;
  source_agent: string;
  source_tool: string;
  status: FindingStatus;
  confidence: number;
}

export interface DocSuggestion {
  file: string;
  line: number;
  kind: "missing_docstring" | "missing_readme_section" | "missing_comment" | "missing_api_doc";
  symbol: string;
  suggestion: string;
  rationale: string;
}

export interface ReconciledFinding {
  primary_fingerprint: string;
  file: string;
  line: number;
  contributing_agents: string[];
  agreement: boolean;
  confidence: number;
  merged_explanation: string;
  conflict?: string | null;
  priority: number;
}

export interface RepoProfile {
  total_files: number;
  total_directories: number;
  package_manager: string | null;
  frameworks: string[];
  languages: Record<string, number>;
  primary_language: string | null;
}

export interface TestCoverageDetail {
  measured: boolean;
  score: number;
  source_files: number;
  test_files: number;
  test_cases: number;
  source_symbols: number;
  modules_with_tests: number;
  module_coverage_pct: number;
}

export interface AuditReport {
  run_id: string;
  repo_id: string;
  repo_source: string;
  timestamp: number;
  findings: Finding[];
  files_scanned: number;
  chunks_indexed: number;
  is_first_run: boolean;
  doc_suggestions: DocSuggestion[];
  reconciled_findings: ReconciledFinding[];
  architecture_explanation: string;
  repo_profile: RepoProfile;
  test_coverage: TestCoverageDetail;
  /** Findings/suggestions that kept a heuristic or placeholder description
   *  because every model provider was unavailable during the run. Detection
   *  is deterministic and unaffected — only the prose is missing. */
  degraded_suggestions: number;
}

export interface RepoHealthScore {
  overall: number;
  security: number;
  quality: number;
  documentation: number;
  architecture: number;
  test_coverage: number;
  technical_debt: number;
  /** False when the repo had no source to judge — the UI must show
   *  "not measured" rather than a 0 the user can't act on. */
  test_coverage_measured: boolean;
}

export interface RepositorySummary {
  repo_id: string;
  repo_source: string;
  run_count: number;
  first_run_ts: number;
  last_run_ts: number;
}

export interface RecurringFinding {
  fingerprint: string;
  run_count: number;
  file: string;
  line: number;
  category: string;
  rule: string;
  title: string;
  severity: Severity;
  last_seen_ts: number;
}

export interface KnowledgeBaseStats {
  repo_id: string | null;
  embedding_dim: number;
  total_chunks: number;
  indexed_repositories: number;
  per_repo: { repo_id: string; chunks: number }[];
  top_files: { file: string; chunks: number; characters: number }[];
}

export interface AuditWithHealth {
  report: AuditReport;
  health_score: RepoHealthScore;
}

export interface FixProposal {
  finding_fingerprint: string;
  file: string;
  patch: string;
  pr_title: string;
  pr_description: string;
  commit_message: string;
  suggested_unit_test: string;
  suggested_integration_test: string;
  estimated_impact: "low" | "medium" | "high";
  estimated_confidence: number;
}

export interface ModelRunResult {
  provider: string;
  model: string;
  response: string;
  latency_ms: number;
  token_estimate: number;
  confidence: number;
  error?: string | null;
}

export interface ModelComparison {
  prompt: string;
  results: ModelRunResult[];
  agreement: boolean;
  differences: string;
  merged_answer: string;
  reasoning_summary: string;
}

export interface RunListItem {
  run_id: string;
  repo_id: string | null;
  repo_source: string;
  ts: number;
  status: string;
  /** Persisted at run completion. Null for in-flight runs and for runs
   *  recorded before health-score persistence existed. Having these on the
   *  list response is what lets the Memory page build its charts from one
   *  request instead of one `GET /api/audits/{id}` per run. */
  health_score: RepoHealthScore | null;
  files_scanned: number | null;
  chunks_indexed: number | null;
  finding_count: number;
  severity_counts: Record<Severity, number>;
}

export type AgentStageStatus = "completed" | "running" | "pending" | "error";

export interface PipelineStage {
  agent: string;
  status: AgentStageStatus;
  duration_seconds: number | null;
  current_file: string | null;
}

export interface AuditProgress {
  run_id: string;
  status: "pending" | "running" | "done" | "error";
  percent: number;
  stages: PipelineStage[];
  error?: string | null;
}

export interface TraceEvent {
  run_id: string;
  ts: number;
  actor: string;
  event: string;
  [key: string]: unknown;
}

export interface RunComparison {
  run_a: string;
  run_b: string;
  new_findings: Record<string, unknown>[];
  fixed_findings: Record<string, unknown>[];
  recurring_findings: Record<string, unknown>[];
  severity_changes: Record<string, unknown>[];
  health_score_a: RepoHealthScore;
  health_score_b: RepoHealthScore;
  health_score_delta: number;
  trend_summary: string;
}

export interface FileTreeNode {
  name: string;
  type: "file" | "dir";
  path: string;
  children?: FileTreeNode[];
}

export interface FileTreeResponse {
  run_id: string;
  tree: FileTreeNode;
  file_count: number;
}

export interface FileFindingRef {
  fingerprint: string;
  line: number;
  severity: Severity;
  title: string;
  rule: string;
  source_agent: string;
  confidence: number;
}

export interface FileContentResponse {
  run_id: string;
  path: string;
  language: string;
  content: string;
  findings: FileFindingRef[];
}

export interface GitHubMetadata {
  available: boolean;
  reason?: string;
  owner?: string;
  name?: string;
  full_name?: string;
  description?: string | null;
  default_branch?: string;
  language?: string | null;
  size_kb?: number;
  stars?: number;
  forks?: number;
  open_issues?: number;
  watchers?: number;
  license?: string | null;
  topics?: string[];
  is_fork?: boolean;
  archived?: boolean;
  created_at?: string;
  pushed_at?: string;
  html_url?: string;
  last_commit_author?: string | null;
  last_commit_message?: string | null;
  last_commit_date?: string | null;
}

export interface ModelInfo {
  id: string;
  model: string;
  live: boolean;
}
