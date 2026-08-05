# prompts.md — AI Interaction Log

This file records the significant AI-assisted interactions used while building AutoAudit AI.  
Minor autocomplete, syntax fixes, and small documentation requests are intentionally omitted.

---

# Week 5 (Second Half) — Project Scaffold & Architecture

## 1. Project structure

**Goal**

Create the initial project structure for a multi-agent code auditing system.

**Prompt**

"Design a Python package structure for an AI code auditing project with separate agents, memory, tools, LLM clients and a CLI entrypoint."

**Result**

Created the initial project layout:

- agents/
- tools/
- memory/
- llm/
- cli.py
- config.py
- schemas.py
- tracing.py

**Review**

Kept the overall structure but renamed a few modules for clarity and separated tracing into its own module.

---

## 2. CLI entrypoint

**Goal**

Create an entrypoint that can execute an audit from the command line.

**Prompt**

"Create an argparse-based CLI with a run command that accepts a repository path and executes a placeholder Supervisor."

**Result**

Implemented:

- autoaudit run <repo>
- placeholder Supervisor
- placeholder report generation

Later replaced the placeholder implementation with the real pipeline while keeping the CLI interface unchanged.

---

## 3. Repository architecture

**Goal**

Plan how repository knowledge and audit history should be stored.

**Prompt**

"Should vector embeddings and audit history share one database or be stored separately?"

**Result**

Decided to use:

- vector_store.db
- audit_history.db

Designed separate schemas for both.

---

## 4. README

**Goal**

Create initial documentation.

**Prompt**

"Generate a README skeleton with architecture, setup instructions and project layout."

**Result**

Created README draft.

Updated later once implementation was complete.

---

# Week 6 — Core Feature Development

## 5. Repository Agent

**Goal**

Read repositories and prepare them for analysis.

**Prompt**

"Implement a repository reader that supports local folders and Git repositories, skips unnecessary files and chunks source code."

**Result**

Implemented:

- local repository support
- Git repository cloning
- language detection
- source chunking
- binary file filtering

**Changes after review**

Added:

- maximum file size limit
- improved binary detection
- fixed repository root handling for Git repositories

---

## 6. Repository Knowledge Base (RAG)

**Goal**

Implement retrieval over repository code.

**Prompt**

"Design a lightweight offline embedding system and vector store suitable for repository retrieval."

**Result**

Implemented:

- hashing-based embeddings
- SQLite vector database
- cosine similarity retrieval

Agents now retrieve only relevant code chunks instead of scanning the entire repository.

---

## 7. Security Agent

**Goal**

Implement security analysis.

**Prompt**

"Integrate Semgrep into a Security Agent while allowing the project to work on systems where Semgrep isn't installed."

**Result**

Implemented:

- Semgrep execution through subprocess
- JSON parsing
- automatic fallback scanner
- source_tool field
- Groq (Llama 3.3 70B) interpretation of findings

---

## 8. Quality Agent

**Goal**

Detect common code quality issues.

**Prompt**

"Implement a Quality Agent using Gemini that detects long functions, missing docstrings and duplicate code."

**Result**

Implemented:

- long function detection
- duplicate code detection
- missing docstrings
- Gemini-generated explanations

---

## 9. Ruff integration

**Goal**

Match the proposal requirement of using a real linter.

**Prompt**

"How can I integrate Ruff into the Quality Agent without removing the existing heuristics?"

**Result**

Added Ruff support.

Workflow became:

Repository

↓

Ruff

↓

Raw lint issues

↓

Gemini

↓

Quality findings

The previous heuristic checks remain available.

---

## 10. Shared Finding creation

**Goal**

Reduce duplicated code.

**Prompt**

"Review both agents for duplicated Finding construction."

**Result**

Introduced a shared make_finding() helper.

Both Security and Quality agents now use identical Finding creation logic.

---

## 11. Audit Memory

**Goal**

Store findings across runs.

**Prompt**

"Implement persistent audit history so a second audit can identify new, fixed and recurring findings."

**Result**

Implemented:

- SQLite audit history
- finding fingerprints
- previous run comparison
- recurring/new/fixed tracking

---

## 12. Report Agent

**Goal**

Generate a single prioritized report.

**Prompt**

"Create a Report Agent that merges Security and Quality findings and includes audit history."

**Result**

Implemented:

- finding prioritization
- markdown reports
- recurring issue section
- audit summary

---

## 13. Testing

**Goal**

Create automated tests.

**Prompt**

"Generate pytest tests for the core modules using mock repositories and mock LLM clients."

**Result**

Created tests for:

- Repository Agent
- Security Agent
- Quality Agent
- Vector Store
- Audit History
- Report Agent
- CLI
- Supervisor

Coverage exceeded the project requirement.

---

# Additional Improvements

## Tool Registry

**Problem**

While reviewing Week 5 requirements I noticed the proposal explicitly mentioned a Tool Registry, but my implementation instantiated tools directly inside the Supervisor.

**Prompt**

"How can I add a lightweight Tool Registry without redesigning the architecture?"

**Result**

Implemented ToolRegistry.

Registered:

- repo-reader
- security-scan
- lint
- embeddings

Supervisor now initializes the registry during startup.

---

## Mock vs Live LLM mode

**Problem**

The project needed to run without API keys for testing.

**Prompt**

"Design a clean mock/live LLM architecture."

**Result**

Implemented:

- AUTOAUDIT_MODE
- mock clients
- live clients
- shared LLM interface

Entire project now runs offline.

---

# Debugging Log

## Git repository path bug

**Problem**

Security Agent failed when auditing repositories cloned from Git URLs.

**Prompt**

"Why does the Security Agent work for local repositories but fail for cloned repositories?"

**Fix**

Repository Agent now returns the resolved repository root.

Supervisor passes that path directly to downstream agents.

---

## Audit history status bug

**Problem**

Recurring findings appeared as

FindingStatus.RECURRING

instead of

recurring

inside reports.

**Prompt**

"Why is my Enum printing as FindingStatus.RECURRING even though use_enum_values=True?"

**Fix**

Stored Enum values explicitly using `.value`.

Added a helper inside Report Agent to safely render enums.

---

## Tool Registry import error

**Problem**

After introducing ToolRegistry the test suite failed during collection because the lint module couldn't be imported.

**Prompt**

"Why can't Supervisor import lint from autoaudit.tools?"

**Fix**

Created the missing module and corrected package imports.

All tests passed afterwards.

---

## Long function detection

**Problem**

Initial threshold was too high and produced no findings.

**Prompt**

"What is a reasonable threshold for long function detection on small repositories?"

**Fix**

Reduced threshold from 80 lines to 40 lines.

---

## Duplicate detection

**Problem**

Similarity threshold generated too many false positives.

**Prompt**

"How should I tune cosine similarity for duplicate code detection?"

**Fix**

Adjusted similarity threshold until duplicate detection produced meaningful results.

---

# Final Verification

Verified manually:

- CLI runs successfully.
- Local repositories work.
- Git repositories work.
- Repository Knowledge Base retrieval works.
- Security Agent works.
- Quality Agent works.
- Audit history persists across runs.
- Reports show recurring findings correctly.
- Tool Registry initializes successfully.
- Mock mode works without API keys.
- Test suite passes.
- Coverage exceeds 70%.

Final test result:

- 47 tests passed
- 91% code coverage

---

# Week 7 — Reconciliation, New Agents, Multi-Model Routing, Validation, Performance

## 14. Removing the paid Anthropic dependency

**Goal**

Satisfy the "at least two LLM providers" requirement without a paid Anthropic key.

**Prompt**

"Replace the second LLM provider with Groq using Llama 3.3 70B, preserving the existing multi-model architecture (routing, comparison, fallback, retry, confidence scoring)."

**Result**

- Removed `llm/claude_client.py`; added `llm/groq_client.py` (OpenAI-compatible Groq chat-completions endpoint, `llama-3.3-70b-versatile`, same mock-mode pattern as the other clients).
- `Config` now reads `GROQ_API_KEY` / `GROQ_MODEL` instead of `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL`.
- Security Agent now runs on Groq instead of Claude; all tests, `.env.example`, and docs updated to match.
- Verified: full test suite green, live CLI run against the mock repo still produces the same finding categories.

---

## 15. Supervisor reconciliation

**Goal**

Cross-check Security/Quality findings that land on the same code and produce a merged confidence + priority.

**Prompt**

"Design a reconciliation step that groups findings from different agents hitting the same or nearby lines, flags agreement/disagreement, and produces a priority ranking — without requiring exact line matches, since agents chunk code differently."

**Result**

Implemented `agents/reconciliation.py`:

- groups findings per-file within a configurable line window
- computes agreement (2+ agents), a confidence score, and a conflict description when severities disagree
- outputs `ReconciledFinding` objects sorted by priority

**Review**

Initial version required exact line matches and almost never grouped anything (Security and Quality chunk differently). Switched to a sliding line-window grouping instead.

---

## 16. Fix Agent

**Goal**

Propose patches without ever touching the repository.

**Prompt**

"Implement a Fix Agent that generates a unified diff, PR title/description, commit message, suggested tests, and impact/confidence estimates for a single finding. It must never write to disk — proposal only."

**Result**

Implemented `agents/fix_agent.py`, producing schema-validated `FixProposal` objects. In mock mode (no live API key) it returns a deterministic, realistic proposal so the agent is fully testable offline; in live mode it goes through the router + validation/repair pipeline. Verified there is no `apply`/`write`/`commit` method anywhere on the class.

---

## 17. Documentation Agent

**Goal**

Detect and draft missing documentation.

**Prompt**

"Implement a Documentation Agent that detects missing docstrings, missing README sections, missing comments on non-trivial logic, and missing API docs on route handlers, then drafts suggested text for each."

**Result**

Implemented `agents/documentation_agent.py` with four heuristic detectors (docstring / comment / README section / API doc gaps) feeding a shared `_draft()` helper routed through the model router.

---

## 18. Multi-model routing, fallback, retry, comparison

**Goal**

Route tasks to the right provider, survive provider failures, and support side-by-side comparison.

**Prompt**

"Build a ModelRouter on top of the existing LLMClient interface with per-task-profile provider preference, timeout-bounded calls, exponential-backoff retries, automatic fallback to the other provider, and a `compare()` that runs all providers in parallel and reports agreement/differences/merged answer."

**Result**

Implemented `llm/router.py`. Timeout is enforced via a worker-thread `Future.result(timeout=...)` so it works uniformly for mock and live calls without touching provider SDKs. Comparison agreement is a deliberately simple, explainable token-overlap heuristic — noted in the docstring as a placeholder for a future embedding-similarity pass.

---

## 19. Output validation / schema guards

**Goal**

Guarantee no malformed structured output enters the pipeline.

**Prompt**

"Implement Pydantic-based validation for LLM JSON outputs with a repair loop (re-prompt with the validation error) and a fallback model, raising a clear error only after all attempts are exhausted."

**Result**

Implemented `llm/validation.py` (`validate_with_repair`). Used by the Fix Agent's live-mode path. Raises `ValidationFailure` (never a malformed object) if repair + fallback both fail; the Fix Agent then falls back to a deterministic proposal rather than letting bad data through.

---

## 20. Caching / incremental scanning

**Goal**

Avoid re-embedding unchanged files on repeat audits.

**Prompt**

"Add a SQLite-backed cache keyed by file content hash so the Repository Agent can skip re-embedding unchanged files, plus a generic embedding cache VectorStore can use."

**Result**

Implemented `tools/cache.py` (`Cache`). `RepositoryAgent` now diffs file hashes against the previous run, only re-embeds changed files, and `VectorStore.add_chunk` accepts an optional cache to reuse embeddings by content hash. Verified via trace logs that a second run of an unchanged repo re-indexes 0 files.

---

## 21. Repository Health Score

**Goal**

Turn a report into a single 0-100 score plus category breakdown for the dashboard.

**Prompt**

"Compute a composite Repository Health Score from an AuditReport: security/quality findings penalize their categories by severity, doc-suggestion density approximates documentation coverage, long-function/duplicate-code counts approximate architecture and technical debt."

**Result**

Implemented `analysis/health_score.py`. Test coverage is currently a fixed neutral placeholder (70) since no coverage tool is wired in yet — documented as an explicit estimate rather than a real measurement.

---

# Week 7 Debugging Log

## Pydantic attribute assignment on AuditReport

**Problem**

First attempt attached `report.doc_suggestions`, `report.reconciled_findings`, `report.root_path`, `report.router` directly onto the returned `AuditReport` — Pydantic v2 rejects assigning undeclared fields.

**Fix**

Added `doc_suggestions` / `reconciled_findings` as real schema fields on `AuditReport`. `root_path` and the (non-serializable) `ModelRouter` instance are kept in an in-memory `Supervisor._run_contexts[run_id]` map instead of on the model, since a live LLM client isn't something that should ever be persisted or serialized.

---

## Test isolation via hardcoded /tmp paths

**Problem**

New cache/fix-agent tests used hardcoded paths under `/tmp` instead of pytest's `tmp_path` fixture. Passed in isolation, failed on repeat full-suite runs because state leaked between runs.

**Fix**

Switched every new test to `tmp_path`. Verified by running the full suite twice in a row.

---

## Final Verification (Week 7)

Verified manually:

- Groq migration: full suite green, live CLI run unaffected, `router.compare()` returns both providers.
- Reconciliation groups cross-agent findings and ranks by priority correctly.
- Fix Agent never has a filesystem-write method; mock-mode output is schema-valid.
- Documentation Agent detects docstring, comment, README, and API-doc gaps on the fixture repo.
- Validation layer raises `ValidationFailure` (never bad data) when repair is exhausted.
- Incremental scanning: second run on an unchanged repo re-indexes 0 files (confirmed via trace log).
- Health score penalizes injected high-severity findings as expected.

Final test result:

- 61 tests passed
- 89% code coverage

---

# Week 7 (cont.) — FastAPI Layer

## 22. HTTP API over the existing Supervisor

**Goal**

Expose the pipeline over HTTP for the frontend, without duplicating any agent logic.

**Prompt**

"Build a FastAPI layer on top of the existing Supervisor: start an audit as a background job and return immediately with a run_id, poll job status/progress, fetch the full report, export Markdown/HTML/JSON, propose fixes for a completed run's findings, compare two historical runs, and run a live multi-model comparison — all backed by the same Supervisor/AuditHistory/ModelRouter code the CLI already uses."

**Result**

- `api/jobs.py` — background-thread job runner + in-memory `JobStore`. Progress/live-agent-status is derived by tailing the same Tracer JSONL log the CLI already writes, so no parallel event system was needed.
- `api/routers/audits.py` — `POST /api/audits`, `GET /api/audits`, `GET /api/audits/{id}/status`, `GET /api/audits/{id}/events`, `GET /api/audits/{id}` (report + health score), `GET /api/audits/{id}/report.{md,html,json}`, `POST /api/audits/{id}/fixes`, `GET /api/audits/compare`.
- `api/routers/models.py` — `GET /api/models/available`, `POST /api/models/compare` (Groq + Gemini side by side).
- `analysis/run_comparison.py` — Week 8 Audit Run Comparison: new/fixed/recurring findings, severity changes, health-score delta, and a plain-language trend summary between any two runs.
- Extended `AuditHistory` with `list_runs`, `get_findings_full`, `diff_between_runs` to support historical lookups after the in-memory job store no longer has a run.

**Verified**

- 13 new API tests via FastAPI's `TestClient`, all passing, using `app.dependency_overrides` per test (not the process-wide `lru_cache` singletons) so tests don't leak state into each other.
- Also smoke-tested with a real `uvicorn` process and `curl`: health check, POST /api/audits → GET status → GET full report → Markdown export → model comparison → Swagger UI at `/docs`, all working over real HTTP.
- Full suite: 74 tests passing, 90% coverage, stable across repeated runs.

---

## Week 7 Debugging Log (cont.)

### AuditReport is immutable at the field level

**Problem**

Same class of bug as the earlier `report.doc_suggestions =` issue: the fixes endpoint needed to filter findings by fingerprint on an already-built `AuditReport` without mutating the original object (which the in-memory job store still holds).

**Fix**

Used Pydantic's `model_copy(update=...)` to produce a filtered copy instead of mutating fields in place.

### SQLite connections across FastAPI's threadpool

**Problem**

`AuditHistory`/`VectorStore` connections aren't safe to share across threads, and FastAPI can dispatch sync path-operations to different threadpool threads per request.

**Fix**

`get_audit_history()` opens a fresh connection per request (closed at the end of each handler) instead of being an `lru_cache` singleton like `get_config`/`get_supervisor`.

---

# Week 7/8 — Frontend

## 23. Design plan

**Goal**

A distinctive dashboard identity, not a templated AI-app look.

**Brainstorm**

Subject: an autonomous multi-agent code reviewer. Audience: engineers/tech
leads who need to trust AI-generated findings quickly. The page's job:
make evidence and confidence legible at a glance, not decorate a generic
SaaS shell.

Rejected the three common AI-generated defaults: cream+serif+terracotta
(reads as a Claude tell), near-black+single-neon-accent, and hairline
broadsheet columns. Instead:

- **Color** (6 named hex): `ink #0A0E13` (page bg, blue-charcoal not pure
  black), `panel #121821`, `panel-raised #19212C`, `hairline #26313D`,
  `signal #4C9EFF` (brand/interactive only, used sparingly), plus a
  *functional* severity palette (`critical #F0495C`, `warning #F5A623`,
  `caution #E8C34D`, `info #59B9B0`, `success #3FBA6D`) that carries real
  information rather than decorating.
- **Type**: Space Grotesk (display — technical, geometric), Inter (body/UI,
  dense-table-readable), IBM Plex Mono (every number — confidence scores,
  line numbers, timestamps, fingerprints — reinforcing "measured, not
  opinion" throughout, not just inside code blocks).
- **Layout**: persistent icon+label sidebar, top bar per page, content in
  bordered cards on the `ink` background.
- **Signature element**: the *Pipeline Rail* — an animated node graph of
  the real, fixed agent execution order (Supervisor -> Repository ->
  Security -> Quality -> Documentation -> Report) with a traveling
  scan-beam animation on the active edge while a run is in progress.
  Numbered/sequential treatment is justified here because the pipeline
  genuinely is a fixed sequence, unlike a generic "01/02/03" feature list.

**Self-critique before building**

Checked the plan against the three clichés again: no cream/serif, no
single acid accent (severity colors do the accent work, brand blue is
used only for interactive/active state), no dense hairline broadsheet
grid (this is a data-dense operational UI, so bordered cards with
generous padding suit it better). Kept the plan as drafted.

## 24. Frontend build

**Prompt**

"Scaffold a React + TypeScript + Vite + Tailwind dashboard against the FastAPI backend: Dashboard, Repository, Audit (live), Findings, Fixes, AI Comparison, Memory (trend + run comparison), Reports (exports), Settings. Every async action needs loading/empty/error states. No shadcn primitives beyond what's actually needed — build a small design-system component set instead."

**Result**

- Scaffolded with `npm create vite@latest -- --template react-ts`, added Tailwind v4 (CSS-first `@theme`), React Router, TanStack React Query, Framer Motion, Recharts, lucide-react.
- Built `src/components/ui/*` (Card, Badge, Button, EmptyState, Skeleton) and feature components (Sidebar, TopBar, PipelineRail, HealthGauge, FindingCard, StatCard).
- All 9 pages implemented against the real API via a typed `src/lib/api.ts` client — no mock data in the frontend; every page's loading/empty/error state was exercised against the live mock-mode backend during testing.
- `RunContext` (localStorage-backed) tracks the "active run" across pages so starting an audit on the Dashboard and switching to Findings/Fixes/Reports shows the same run without re-selecting it.

**Verified**

- `npm run build` (tsc -b && vite build): clean, zero errors.
- `npx oxlint src`: 0 errors, 2 harmless warnings (a memoization nit and a fast-refresh file-organization nit), both reviewed and left as-is or fixed.
- End-to-end integration test: ran the real FastAPI backend + `vite dev` together, curled through the dev-server's `/api` proxy (the same path the browser uses) — health check, start audit, poll to completion, all confirmed working against the live backend, not a mock.

**Known gaps** (documented in `frontend/README.md`): no VS Code-style file-tree/code-explorer with click-to-scroll-to-finding yet (Findings page shows evidence as a text snippet instead); no light theme; no auth (matches the backend).

---

# "Complete the remaining gaps" round

The person asked for every remaining item in `docs/CHECKLIST.md` to be completed, in a specific priority order, before treating the project as a final submission.

## 25. Repository Explorer, PDF export, GitHub metadata

**Prompt**

"Complete: (1) VS Code-style Repository Explorer with syntax highlighting, file tree, click-to-finding navigation, highlighted evidence, and suggested fixes. (2) PDF export for audit reports with professional formatting. (3) Repository Overview via the GitHub API (stars, forks, branch, last commit, open issues, size)."

**Result**

- Backend: `GET /api/audits/{run_id}/files` (tree) and `/file` (content + mapped findings), served from an in-memory run context (`Supervisor._run_contexts`) rather than disk, so it works for cloned repos whose temp directory has already been cleaned up.
- Frontend: `FileTree.tsx` (recursive), `CodeViewer.tsx` (Prism syntax highlighting via `PrismLight` with explicit per-language registration to keep the bundle down, severity-colored line backgrounds, click-to-jump), `ExplorerPage.tsx` wiring it together with a findings sidebar and an inline "Suggest Fix" action. Lazy-loaded to keep it out of the main JS bundle.
- `ReportAgent.render_pdf()` using reportlab/platypus — cover, color-coded severity table, health-score table, trend section, per-finding blocks. `GET /api/audits/{run_id}/report.pdf`.
- `tools/github_client.py` — best-effort GitHub REST API metadata (never blocks the pipeline; returns `None`/`{"available": false}` for non-GitHub sources or on any request failure), `GET /api/repository/metadata`, and a debounced live-updating card on the Repository page.

**Verified**

- PDF: rasterized a generated page to PNG and visually inspected it (not just "the file exists") — confirmed title, metadata, color-coded tables, and findings render correctly.
- Explorer: live end-to-end check against a running server — tree, file content, and findings-with-line-numbers all confirmed via curl.
- GitHub client: 7 tests with mocked `requests.get` (never hits the real GitHub API in CI), covering URL parsing, success, 404, and network-failure paths.

## 26. Advanced filters, trend charts

**Prompt**

"Complete the remaining advanced filters (AI model, confidence, folder, file path, finding type, status). Add dedicated Severity Trend, Confidence Trend, and Issue Frequency charts to the Trend Dashboard."

**Result**

- Added a real `confidence` field to `Finding` (previously only `ReconciledFinding` had one), populated via a new `ReconciliationEngine.confidence_by_fingerprint()` that propagates a group's confidence to *every* member, not just the highest-severity primary.
- Findings page: AI model (derived from `source_agent` → provider mapping), finding type/category, file-path substring, minimum-confidence slider, and status, alongside the existing severity/agent/search filters.
- Memory page: four charts (Health Score, Confidence, Severity multi-line, Issue Frequency bar) using data already fetched for the trend/timeline view — no extra API calls.

**Verified** — 87 backend tests passing at this point; frontend build clean; confirmed via a direct Python script that mock-mode confidence values look sane (0.85 for cross-agent-agreed findings, lower for solo ones).

## 27. Vitest + React Testing Library, GitHub Actions CI

**Prompt**

"Add frontend automated tests using Vitest and React Testing Library. Add a GitHub Actions CI workflow that builds the backend and frontend, runs all tests, and reports coverage."

**Result**

- Set up Vitest + RTL + jsdom from scratch (`vitest.config.ts`, `src/test/setup.ts`). 53 tests: utilities, the typed API client (mocked `fetch`), 5 components, and 2 page-level integration tests — the Findings-page one exercises the *actual* filter logic (severity/search/confidence/category) against mocked API responses, not just "does it render".
- `.github/workflows/ci.yml`: backend job (`pytest --cov-fail-under=80`), frontend job (`oxlint` + `vitest run --coverage` + `build`), and a Docker build-sanity job.

**Verified** — All 53 frontend tests passed on the first real run. Every command in the CI workflow (except the Docker build steps) was run locally before being committed to the workflow file, including the exact `--cov-fail-under=80` flag.

## 28. RAG improvements, parallel agent execution

**Prompt**

"Improve the RAG layer with hybrid retrieval, metadata filtering, batch embedding, and batch retrieval where practical. Improve parallel execution of independent worker agents where possible."

**Result**

- `embeddings.embed_texts_batch()` — vectorized batch embedding, verified to produce bit-identical output to the per-text `embed_text()`.
- `VectorStore.query()` gained `file_prefix`/`file_extension` metadata filtering and hybrid retrieval (blended cosine + keyword-overlap score, `keyword_overlap_score()` in `embeddings.py`), plus `add_chunks_batch()` and `batch_query()`. `RepositoryAgent` switched from looping `add_chunk()` to a single `add_chunks_batch()` call.
- Security, Quality, and Documentation agents — previously sequential — now run concurrently via `ThreadPoolExecutor` in `Supervisor.run()`, since none depends on another's output.

**Debugging note**

Parallelizing the agents surfaced a real correctness question, not just a performance one: `VectorStore` and `Tracer` were both single-connection/single-writer objects never designed for concurrent access from multiple threads. Fixed by opening the SQLite connection with `check_same_thread=False` and wrapping every method in an internal `threading.RLock` (`VectorStore`), and adding a lock around both the in-memory event list and the JSONL file write (`Tracer`). Verified genuine concurrency (not just "the code allows it") via trace-event timestamps showing all three agents' `scan.start` events landing within ~1ms of each other, plus 5 repeated full-suite runs with no flakiness.

## 29. Auth placeholder

**Prompt**

"Add an authentication placeholder and any remaining production-quality improvements that are still listed as incomplete."

**Result**

`api/auth.py` — a `BaseHTTPMiddleware` checking `Authorization: Bearer <key>` against `Config.api_key` (from `AUTOAUDIT_API_KEY`), off by default. Constant-time comparison (`hmac.compare_digest`) so response timing can't leak the key.

**Debugging note**

First version added the auth middleware *after* `CORSMiddleware` in `create_app()`. Starlette wraps middleware in reverse add-order, so this made CORS the *inner* layer — meaning a 401 response from the auth check never passed back through CORS's header-injection logic, and a browser client would see an opaque CORS failure instead of a readable 401. Caught by a dedicated test (`test_cors_headers_present_on_401_response`) that failed on the first run; fixed by swapping the middleware registration order so CORS wraps outermost.

Also caught during review, before it shipped: the middleware's first draft called the process-wide `get_config()` singleton directly, which would have bypassed FastAPI's `dependency_overrides` and broken per-test config isolation (every test would've shared one real config instance). Fixed by resolving config through `request.app.dependency_overrides.get(get_config, get_config)()` — the same override FastAPI's own `Depends()` machinery would use.

**Verified** — 8 dedicated tests (disabled-by-default, missing/wrong/correct key, docs always exempt, malformed header, the CORS regression above) plus a live check against a real running server with `AUTOAUDIT_API_KEY` set.

---

# Final gap-analysis round

The person re-supplied the original requirements document (now with an updated Section 4 specifying Gemini as primary provider, Groq as secondary, an explicit provider-agnostic interface, per-agent configurability, health checks, and automatic failover) and asked for a systematic gap check against it before any further work.

## 30. Gap analysis

Read the full updated document against the current implementation, line by line, and reported five concrete gaps rather than assuming everything was covered:

1. Multi-model routing didn't match the more specific updated spec (hardcoded provider dicts in two places, no health checks, no per-agent configurability, no explicit primary/secondary designation).
2. Documentation Agent didn't generate an "architecture explanation".
3. Repository Overview was missing framework/package-manager/total-directories detection.
4. Repository Explorer didn't display confidence scores despite that being explicitly listed.
5. Live Agent Execution Visualization was missing per-agent duration and current-file granularity.

Also flagged, transparently, that Section 5 still says "Claude only / Gemini only / Both" — a leftover from before Claude/Anthropic was removed per an earlier explicit instruction — and stated that Groq would be kept, not Claude reintroduced, rather than silently deciding either way.

## 31. Provider registry, health checks, per-agent configuration

**Result**

- `llm/registry.py`: `ProviderRegistry` — the single place providers are constructed (`register()` to add a new one, zero agent-code changes), plus `for_agent(name)` resolving a per-agent config override or falling back to the system primary, `health_check_all()`, and `healthy_provider_order()` for failover ordering.
- `PRIMARY_PROVIDER = "gemini"`, `SECONDARY_PROVIDER = "groq"` as explicit constants.
- `Config` gained `security_agent_provider` / `quality_agent_provider` / `documentation_agent_provider` / `fix_agent_provider`, each an env-var override, defaulting to the previously-hardcoded assignment (Security/Fix on Groq for precision, Quality/Documentation on Gemini for volume) — now a config change instead of a code change.
- `LLMClient.health_check()` + `ProviderHealth`, and `GET /api/models/health`.
- `Supervisor` and `api/routers/models.py` rewritten to pull clients from the registry instead of constructing `GroqClient`/`GeminiClient` inline in two separate places.

**Verified** — 12 new tests including a fake-provider registration test (proving the "pluggable without touching agent code" claim) and a forced-unhealthy-provider test proving the failover ordering actually demotes it. 122 backend tests passing. Live check: `/api/models/available`, `/api/models/health`, and a full audit run, all over real HTTP.

## 32. Architecture explanation

**Result** — `DocumentationAgent.generate_architecture_explanation()`, grounded in a deterministic structural digest (directory tree, file counts, language distribution, entry-point filename hints) built before any LLM call, so the model has real data to describe rather than something to invent. New `architecture_explanation` field on `AuditReport`, new "Architecture Overview" card on the Repository page.

**Verified** — 3 tests, including one asserting the explanation contains the real file count (proof it's grounded, not generic filler). Live check via curl confirmed the mock-mode output correctly reflects the actual scanned file/directory count.

## 33. Repository profiler

**Result** — `tools/repo_profiler.py`: package-manager detection via lockfile/manifest presence (12 indicators, ordered by specificity — a lockfile beats a bare `requirements.txt`), framework detection via dependency-file content or characteristic files (deliberately conservative — only reports concrete evidence, never guesses from naming conventions), plus total file/directory counts and primary-language detection. New `RepoProfile` schema, wired into `AuditReport` and the Repository page.

**Debugging note** — First wiring attempt assigned the plain dataclass returned by `profile_repository()` directly to `AuditReport.repo_profile` (a pydantic field). Pydantic v2 doesn't validate on assignment by default, so this wouldn't have raised immediately — it would have silently stored an unvalidated dataclass instance that FastAPI's JSON serialization likely couldn't handle correctly. Caught before running any tests, by tracing the type through rather than assuming assignment "just works"; fixed with an explicit `RepoProfileSchema(**dataclasses.asdict(...))` conversion.

**Verified** — 10 tests, 100% coverage on the module. Live check confirmed real profile data (file/directory counts, detected language) returned via the API.

## 34. Explorer confidence display

**Result** — The Explorer's per-file findings payload (`GET /api/audits/{run_id}/file`) didn't include `confidence` at all — a real, simple gap. Added it to the endpoint response and displayed it in three places: the findings-in-file sidebar list, the AI Explanation detail panel, and the code-line hover tooltip.

**Verified** — Extended the existing explorer API test to assert every returned finding has a `confidence` in `[0, 1]`. Live check confirmed real confidence values (0.85, 0.1) coming through for a mock-mode run.

## 35. Per-agent duration and current-file

**Result** — `api/jobs.py`'s `progress()` rewritten to compute per-stage duration from tracer start/done event timestamp pairs, and to surface the most recent file each agent is processing via a new `processing_file` trace event, added to Security, Quality, and Documentation agents' file-processing loops. Displayed under each node on the full (Audit-page) Pipeline Rail.

**Verified** — Live check against a running server confirmed `processing_file` events are genuinely emitted with real file paths per agent (`security_agent -> src/app.py`, etc.). Duration values populate correctly for completed stages. Noted honestly in the checklist that mock mode completes in milliseconds, so a single poll during a live run couldn't reliably catch the "in-progress with a current file" mid-state in this environment — the underlying signal is confirmed real via the trace log, and would show live on any slow-enough (real LLM-backed) run.

## 36. Bug found during regression testing: non-deterministic embeddings

While re-running the full test suite repeatedly after the changes above (a habit maintained throughout this project, not a one-off), `test_add_and_query_finds_relevant_chunk` failed once, then passed on immediate re-run with no code changes — a classic flaky-test signature. Rather than dismiss it as flakiness or add a retry/skip, traced it to the actual cause.

**Root cause** — `tools/embeddings.py`'s hashing-trick embedding used Python's built-in `hash()` on tokens. `hash()` on strings is randomized per-process (`PYTHONHASHSEED`) by design in CPython, for security reasons (hash-flooding attack resistance) — meaning the *same text* embeds to a *different* vector every time the process restarts. Within one `pytest` run, all tests share one hash seed, so this wasn't visible as within-run flakiness; it only showed up as between-run variance, which is exactly what was observed. This is more than a test-flakiness issue: the file-hash embedding cache (`tools/cache.py`) is built on the assumption that `embed_text(text)` is a pure, stable function of `text` — with `hash()`, that assumption was false across server restarts, meaning cached embeddings from a previous run could silently mismatch newly-computed ones after any restart.

**Fix** — Replaced `hash(token)` with `zlib.crc32(token.encode("utf-8"))`, which is stable across processes and platforms.

**Verified**

- Ran `embed_text()` on the same input in three separate `python -c` process invocations — confirmed bit-identical output (previously, this would have varied).
- Ran the full backend suite 8 times in a row post-fix: 134/134 passing every time (previously intermittent).
- Added `test_embed_text_deterministic_across_processes`, which spawns a real subprocess and compares its output to the current process's — not just an in-process assertion, since the bug was specifically about *cross-process* behavior.
- Confirmed the new test actually catches this bug class: temporarily reverted the fix, ran the test 3 times (failed 3/3), restored the fix, ran it again (passed) — a regression test is only worth as much as its proven ability to fail when the bug it's guarding against is present.

## 37. Full-project audit: "check this project thoroughly, memory and health score displays look wrong"

**Prompt** — Review the whole project against the original proposal, test it on a real repository, and fix what's broken. Suspicion flagged: the memory and health-score displays aren't showing correct values.

The suspicion was correct, and tracing it turned up several defects that had no test covering them. Verified by running the real pipeline against `pallets/click`, `pallets/flask` and `psf/requests`, not just the mock fixture.

### 37.1 Health score saturated at 0 for any real repository (critical)

**Symptom** — Reading the persisted scores out of the user's own `audit_history.db`:

```
flask : {"overall":43,"security":74,"quality":0,"documentation":93,"architecture":0,"test_coverage":70,"technical_debt":0}
click : {"overall":37,"security":100,"quality":0,"documentation":0,"architecture":0,"test_coverage":70,"technical_debt":0}
```

Three categories reading exactly 0 on two unrelated, healthy, widely-used libraries is not a measurement — it's a saturated scale.

**Root cause** — `_category_score` started at 100 and subtracted a flat penalty per finding with no normalisation by repository size. flask's 54 low-severity quality findings × 2 points = 108, so quality floored at 0. Architecture (`long_fn * 4`) and technical debt (`(long_fn + dup) * 5`) floored the same way. The score was a function of how big the repo was, not how good it was — and once floored, no amount of real improvement could move it.

**Fix** — Rewrote scoring around **penalty density per scanned file**, mapped through `100 / (1 + density/D)`. `density == D` scores 50; the curve approaches 0 asymptotically instead of clamping. Severity is weighted (high 10 / medium 4 / low 1 / info 0.25) rather than flat. Constants and rationale documented in `docs/ARCHITECTURE.md`.

**Verified** — Same three repos now score 72 / 82 / 74 with every category differentiated. Added `tests/test_health_score.py`, including the property that actually matters: the same finding set must score higher in a larger repo, and a large repo must not saturate.

### 37.2 Findings already fixed were counted against the score

**Root cause** — `ReportAgent.build_report` returns `findings + fixed`, where the `fixed` entries are reconstructed by `diff_against_last` for issues that are *no longer in the code*. `compute_health_score` and the Dashboard's severity tiles both iterated the whole list. Fixing an issue could therefore leave the score flat or make the "High" tile go **up**.

**Fix** — `AuditReport.active_findings()` / `summary_counts()` exclude `fixed`; the health score filters them out in every category; the Dashboard counts only open findings and reports "N fixed since the previous run" separately. The Fix Agent also no longer burns its budget proposing patches for code that isn't there.

**Verified** — `test_fixed_findings_do_not_count_against_the_score` asserts the score is byte-identical with and without resolved findings. End-to-end: injected a secret + `eval` + a 62-line function into a clean repo (91 → 55), removed them (55 → 91), and confirmed the comparison view reported 3 fixed and +36.

### 37.3 `test_coverage` was a hardcoded 70

**Root cause** — A literal `test_coverage = 70` carrying 10% of the composite. Identical for a repo with 400 tests and a repo with none — noise weighted as signal, and the mock behaviour the spec asked to be removed.

**Fix** — New `autoaudit/analysis/test_coverage.py` measuring two observable properties: share of source modules with a matching or referenced test file (60%), and test cases per source symbol (40%). Deliberately **not** presented as executed line coverage — AutoAudit doesn't run an untrusted repo's suite, and the UI shows the underlying counts so the heuristic is legible. When a repo has no source to judge, the category reports "not measured" and is dropped from the composite with the remaining weights renormalised, rather than scoring 0.

**Verified** — flask reports 49 test files / 404 cases / 25-of-30 modules covered → 90. A source-only fixture with no tests scores 0. The Dashboard was also never rendering this bar at all, so the breakdown couldn't explain the total; it now does.

### 37.4 The Fixes page returned 500 on every request (critical)

**Root cause** — `Supervisor.propose_fixes` called `FixAgent(..., files=files, ...)`, but `FixAgent.__init__` had no `files` parameter. `TypeError` on every call. A comment referenced `extract_source_snippet_from_content` as the reason for passing it — that function was never written. So the feature was half-implemented and had been failing for every user of the page.

There was a second bug hiding behind the first: for a cloned repo, `root_path` points at a temp directory that `Supervisor.run` has already deleted via `cleanup_if_temp`, so the disk-based snippet reader returned `""` and the model was asked to write patches for code it was never shown — the documented cause of hallucinated placeholder patches.

**Fix** — Implemented `extract_source_snippet_from_content` and gave `FixAgent` the in-memory `FileRecord` index as its primary context source, falling back to disk.

**Verified** — Endpoint returns 200 with grounded patches. The existing `test_propose_fixes_endpoint` had been failing on `main` and now passes.

### 37.5 Memory page charted every repository on one line

**Root cause** — `MemoryPage` fetched *all* runs regardless of repository and plotted them as a single trend. With flask, click, a Hello-World clone and a personal repo in one database, the "health score trend" was repo-to-repo variance, not a trend. It also issued one `GET /api/audits/{run_id}` per run (an N+1 fan-out) purely to read a few numbers off each report, and the spec's Knowledge base / Chunks / Embeddings and Recurring findings sections had no backend and were simply absent.

**Fix**
- `GET /api/audits?repo_id=` scoping, plus `GET /api/audits/repositories` and a repository selector in the UI.
- `list_runs` now returns each run's persisted health score, severity counts, `files_scanned` and `chunks_indexed` — one request builds the whole timeline.
- Persisted `files_scanned`/`chunks_indexed` on the `runs` table (with migration), so historical runs stop reporting 0 chunks and a files count guessed from distinct finding paths.
- New `GET /api/audits/recurring` computing recurrence across the *whole* history in SQL, so an issue that was fixed and later reintroduced still counts.
- New `autoaudit/api/routers/memory.py` exposing knowledge-base stats and a live query against the vector store.
- The "Compare" button previously rendered but did nothing (the query ran off the select values); it now actually triggers the comparison, and the run pickers reset when the repository changes.

**Verified** — `tests/test_memory_api.py` (17 tests) covers scoping, recurrence including the fixed-then-reintroduced case, the migration path from a pre-existing DB, and the HTTP surface. Frontend `MemoryPage.test.tsx` asserts the repo filter is actually sent and that no per-run fan-out occurs.

### 37.6 Smaller defects found along the way

- **`get_audit_history` bypassed FastAPI's `dependency_overrides`** by calling `get_config()` directly, so tests that redirected config at a tmp directory were still opening and writing to the real `./data/audit_history.db`. Now injected via `Depends`.
- **Findings page filtered on categories that don't exist.** `FindingCategory` listed `"documentation"` and `"architecture"`; the backend only ever emits `security`, `quality`, `docs`. Those two options could only return zero results, and real `docs` findings had no filter at all.
- **`diff_against_last` assigned `status` inconsistently** — the enum member on a repo's first run, the plain string on every later run. Because `FindingStatus` is a str-mixin enum this passes `isinstance(x, str)` while rendering as `"FindingStatus.NEW"`.
- **Stale test**: `test_quality_agent_flags_missing_docstring` asserted behaviour deliberately moved to the Documentation Agent. Rewritten to lock in the single-owner split rather than deleted.
- **`.env.example` contained live Groq, Gemini and GitHub credentials** and is explicitly un-ignored in `.gitignore`. The repository has no commits yet, so nothing has leaked, but the keys were staged to be published on the first push. Replaced with empty placeholders — **the exposed keys should still be rotated**, since they've existed in a working tree in plaintext.

**Final state** — 164 backend tests at 88% coverage, 64 frontend tests, clean `tsc -b`, zero new lint warnings.


## 38. Gemini 503 killed a ~400s Flask audit at its final step

**Prompt** — A live run died with `Gemini API server error after 4 attempt(s): 503 ... "This model is currently experiencing high demand" ... UNAVAILABLE`, after Repository (38s) → Security (40s) → Quality (133s) → Docs (360s). Question asked: is the earlier batching/spacing/retry work the right fix for this, or is something else needed?

**Answer: that work was correct, but for a different failure.** It was built to fix HTTP **429**, and it does. This is **503**, and the two need opposite responses:

| | 429 | 503 |
|---|---|---|
| Whose limit | ours — our key, our request rate | the provider's — model saturated for everyone |
| Does batching/spacing help? | **yes**, that's exactly the lever | **no**, asking slower changes nothing |
| Real remedy | fewer/larger requests, higher quota | another provider, or wait |

Batching harder against a 503 just makes each doomed request bigger. The remedy is a different provider — and the project already had one: `ModelRouter` with Gemini→Groq fallback, listed as a Week 7 requirement.

### 38.1 The agents were bypassing the router entirely

**Root cause** — `DocumentationAgent._resolve_client()` did `self.router.clients.get(self.provider)` — reaching *past* the router to grab the raw client, then calling `client.complete()` directly. Every bit of fallback/retry/timeout logic the router exists to provide was skipped. Its own module docstring claimed the opposite ("goes through the model router so it benefits from routing/fallback"), documenting an intent the code didn't implement. `QualityAgent` and `SecurityAgent` were worse — constructed with a bare `LLMClient` and no router at all.

So a healthy, configured, idle Groq provider sat there while a Gemini 503 ended the run.

**Fix** — Added `ModelRouter.complete_text()` returning `(text, error)`, giving agents the plain-string ergonomics they'd reached past the router to get, without giving up failover. All three agents now draft through it. `SecurityAgent`/`QualityAgent` take an optional `router=` so existing constructor calls and tests keep working.

### 38.2 A drafting failure destroyed the whole run

**Root cause** — Any provider exception propagated out of `Supervisor.run()`. Six minutes of completed repository indexing, security scanning and quality analysis were discarded because *text generation* failed at the end.

This inverts the value of the work. Detection is deterministic — Semgrep, heuristics, vector similarity. Only the human-readable description needs a model. The rule now encoded: **never lose a deterministic result because a probabilistic one failed.**

**Fix** — All three agents degrade instead of raising. A finding keeps its file, line, rule, severity and evidence, and carries its raw static-analysis/heuristic message as the description. `AuditReport.degraded_suggestions` counts the affected items and the Dashboard shows a banner, so a placeholder is never mistaken for model output.

### 38.3 Classifying the two failures

Added `ProviderUnavailable(kind="quota"|"capacity")`. Both clients raise it after exhausting their own backoff. The distinction drives the error message — pointing someone at `GEMINI_REQUEST_DELAY_MS` for a 503 sends them tuning a knob that cannot help.

An initial draft had the router *retry* on `kind="quota"`. That was wrong, and writing the test surfaced it: the client has already backed off with `Retry-After` before raising, so router-level retries only delay the failover. Both kinds now fail over immediately; `kind` survives purely as user-facing guidance.

### 38.4 Circuit breaker

**Root cause** — Failover fixed correctness but not cost: *every* subsequent call paid another full retry/backoff cycle to rediscover the same outage. Measured on Flask, Gemini was called **278 times** during one degraded run.

**Fix** — `RouterConfig.unavailable_cooldown_seconds` (45s). A provider that reports itself unavailable is skipped for the window; if all are cooling down, `complete()` returns immediately so callers degrade without blocking.

### 38.5 Two more problems found while fixing the above

- **Router timeout was shorter than the client's.** `RouterConfig.timeout_seconds` was 30s while the clients use a 60s per-request timeout with several backoff retries. Harmless only because nothing was actually routed through the router — the moment the agents were wired up correctly, it would have killed batched drafting calls that were still legitimately in progress. Raised to 240s, with a test asserting it exceeds the client budget.
- **Groq had no retry at all** — a single `requests.post` and `raise_for_status()`. As the *failover target*, a momentary blip on it defeated the entire point of having one. Given the same retry/backoff/classification contract as the Gemini client.

**Verified** — 22 tests in `tests/test_provider_failover.py`, including monkeypatched HTTP layers returning Google's literal 503 body. Plus an end-to-end probe on a real 100-file Flask clone:

| Scenario | Before | After |
|---|---|---|
| Gemini 503, Groq healthy | run aborted | completes, 57 findings, 0 degraded, **147s → 9.8s** (278 → 2 wasted Gemini calls) |
| Both providers 503 | run aborted | completes in 8.6s, 57 findings + 66 doc suggestions intact, 125 degraded and reported |

186 backend tests at 90% coverage, 66 frontend tests, clean `tsc -b`.


## 39. "Generate Fixes" and "Run Comparison" hang

**Prompt** — After the Flask audit, both the Fixes page ("Fix Agent is drafting proposals…") and the AI Comparison page spun for several minutes with no result. Reported as new behaviour.

It was new: **one of the three causes was a regression I introduced in entry 38.** Measured rather than guessed, with a probe that computes each endpoint's worst case and times it against a simulated rate-limited/stalled provider.

### 39.1 One timeout for two incompatible workloads (regression from 38)

Entry 38 raised `RouterConfig.timeout_seconds` 30s → 240s so the newly-routed *batched drafting* calls wouldn't be killed mid-progress. That was right for background work — and wrong for everything else, because the same constant governs the endpoints a human waits on.

Measured worst case for `/api/models/compare` afterwards:

```
240s per attempt x 3 retries x 2 providers, + compare()'s extra LLM judge call
=> 2880s (48 minutes)
```

**Fix** — Split the budget. `timeout_seconds` (240s) for background audit work; `interactive_timeout_seconds` (45s) for anything a user is waiting on, passed via `interactive=True`.

A first attempt applied the interactive budget *per attempt*, which still measured 135s for a stalled provider. Retrying something that just failed to answer within its budget mostly reproduces the same wait, so `interactive=True` now converts the budget into an absolute deadline spanning every retry and every failover. Re-measured: **45.2s**.

### 39.2 The timeout never bounded anything

While testing the above, the probe showed a 1s budget against a 3s provider taking **9.0s** — three attempts each paying the full 3s.

**Root cause** — `_call_with_timeout` ran its worker inside `with ThreadPoolExecutor(...)`. `__exit__` calls `shutdown(wait=True)`, so `future.result(timeout=...)` raised on schedule but the `with` block then blocked until the abandoned call finished anyway. The timeout only ever converted a slow call into a slow call *plus* an error.

This had been latent since the router was written and was invisible until entry 38 actually routed agents through it.

**Fix** — Explicit `shutdown(wait=False)`, letting the abandoned request finish in the background. Verified with `test_timeout_actually_returns_early`.

### 39.3 FixAgent bypassed the router (missed in 38)

Entry 38 fixed exactly this bug in the Documentation, Quality and Security agents. `FixAgent` had it too — `router.clients.get(self.primary_provider)` then `primary.complete(...)` directly — and I missed it. No failover, no timeout, no circuit breaker.

Compounding it: each finding costs up to four model calls (one draft plus `validate_with_repair`'s repair/fallback attempts), findings were processed strictly sequentially, and there was no overall budget. Measured at ~7s per rate-limited call: **~280s for the default ten findings**, with nothing rendered until all of them finished. That is the reported hang.

**Fix** — Routed through `complete_text(interactive=True)`; findings drafted concurrently (4 workers) under one shared 90s deadline; always one proposal per requested finding, with undrafted ones returned as labelled deterministic proposals so the list is never silently truncated. Measured: **10 proposals in 14.0s** against a fully rate-limited provider.

A wrapper (`_propose_one_safely`) ensures one finding's exception can't propagate out of the thread pool and destroy proposals that already succeeded.

### 39.4 The frontend had no timeout at all

`fetch` has none by default, so even a correctly-bounded backend couldn't have saved the UI from a stalled connection — the spinner would spin forever. The AI Comparison page also rendered **nothing** on error: the spinner simply stopped.

**Fix** — `AbortController` on every request (30s default, 120s for model-backed endpoints, deliberately above the server's own budgets so the server's specific message wins). A `PendingWork` component shows elapsed seconds, a progress bar and a "taking longer than usual" warning, and the comparison page now renders errors with a retry button.

### 39.5 A bug my own test caught

`complete_text` didn't forward the new `interactive`/`deadline` kwargs, so `FixAgent`'s calls raised `TypeError`, were swallowed by the batch-safety wrapper, and silently returned fallback proposals — the feature would have looked like it worked while never calling a model. `test_propose_fixes_goes_through_the_router` failed on exactly this.

**Verified** — 13 new tests in `tests/test_interactive_budgets.py`, 7 in `frontend/src/test/apiTimeout.test.ts`, plus end-to-end measurement through the real API:

| Endpoint | Condition | Before | After |
|---|---|---|---|
| `/api/models/compare` | both providers 429 | ~48 min worst case | **7.1s** |
| `/api/models/compare` | provider never answers | unbounded | **45.2s** |
| `propose_fixes` (10 findings) | provider 429 | ~280s, sequential, all-or-nothing | **14.0s**, all 10 returned |

Re-ran the entries 37 and 38 probes to confirm no regression: health score still moves 84 → 51 → 84, repo scoping intact, and the Flask outage run still completes in ~8.5s with 57 findings.

199 backend tests at 90% coverage, 73 frontend tests, clean `tsc -b`, zero lint errors.


## 40. Security stage runs for minutes and stalls the whole pipeline

**Prompt** — Screenshot of a live Flask run: Repository done in 5.5s, **Security still running at 274.1s**, Quality/Docs/Supervisor all sitting at the same ~274s with the bar stuck at 20%. Noted that security took ~40s in an earlier run.

### 40.1 The theory I had was wrong

My first hypothesis was retry amplification from entries 38–39 — the router retries (3×) wrapping a client that also retries (4×), i.e. up to 24 requests for one finding. Plausible, and it would have been my answer without checking.

I measured it instead: 10 findings through the router vs. calling the client directly, under a healthy provider and one 429ing every third request.

```
healthy      : 1.0x  (10 HTTP reqs both ways)
rate-limited : 1.0x  (14 HTTP reqs both ways)
```

**No amplification.** The `ProviderUnavailable` short-circuit added in entry 38 already prevents the nested-retry case. Worth stating plainly: the obvious suspect was innocent, and shipping a "fix" for it would have added complexity for nothing.

### 40.2 The actual cause

Two facts, found by inspecting rather than guessing:

1. **Security was the only agent never batched.** Quality and Documentation were converted to batched drafting in earlier weeks specifically to stop rate-limit problems. Security was missed — and it's the worst place to leave unbatched. The offline fallback scanner finds **3** issues in Flask; `semgrep --config=auto` (which the reporter has installed, and I don't) finds **hundreds**. Every one was its own sequential round trip.

2. **Security's model calls ran inside the Supervisor's *parallel detection* phase.** Quality and Documentation finished detecting in seconds, then blocked waiting on Security's futures. That's exactly what the screenshot shows: three stages all reporting the same 274s, one spinner, 20% progress. The other two weren't working — they were queued.

### 40.3 Fix

- Split `SecurityAgent` into `detect()` / `draft()`, matching the other two agents. `detect()` is static analysis plus vector retrieval — fully deterministic — so the parallel phase is now free of model calls entirely.
- Batched `draft()` using the existing `###ITEM n###` protocol, with `SECURITY_AGENT_BATCH_SIZE` (default 8) and per-item retry only when a batch response won't split cleanly.
- Supervisor drafts Security first in the sequential drafting phase — different provider from the other two, and its findings are the highest-value output.
- Timed the Semgrep subprocess and put `seconds` in the `static_analysis.done` trace event. `--config=auto` fetches rule packs over the network and can run for minutes; that time was previously invisible and looked like the agent hanging. The troubleshooting guide now explains how to tell the two apart.

**Verified** — measured at 1.2s/request:

| Findings | Before | After | Speedup |
|---|---|---|---|
| 10 | 12s | 2.4s | 5.0× |
| 50 | 60s | 8.4s | 7.1× |
| 200 | 240s | 30.1s | 8.0× |
| 500 | 600s | 75.7s | 7.9× |

14 tests in `tests/test_security_batching.py`, covering: request count scaling as `ceil(N/8)` across several sizes, no cross-finding text misattribution, metadata survival, unparseable-batch fallback, one degradation per batch (not per item) during an outage, `detect()` making zero model calls, and two structural guards asserting the parallel phase contains `security_agent.detect` and *not* `security_agent.run` — so this specific stall can't come back silently.

Re-ran the entries 37–39 probes: health score still 84 → 51 → 84, repo scoping intact, Flask outage run completes with 57 findings, all interactive bounds hold.

213 backend tests at 91% coverage, 73 frontend tests.


## 41. Gemini "thinking" was making a small repo take 270s to draft

**Prompt** — Screenshot of a run on a small personal repo. Entry 40's fix is visible and working: Repository 2.2s, **Security 0.1s** (was 274s). But Quality then took 274.1s and Documentation was at 392.3s and climbing. Noted the project isn't big.

The finding count wasn't the problem this time — a ~20-finding repo is 3 batches. 274s for 3 requests is ~90s each, which is nothing like a Gemini Flash completion.

### 41.1 The request had no `generationConfig` at all

```python
payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
```

For `gemini-2.5-flash` that means **thinking is enabled by default** — the model performs extended internal reasoning before answering. Nothing this project asks Gemini for benefits from it: every prompt is "write 1-2 sentences describing this finding" or "write a docstring for this function".

The arithmetic matches the report exactly. A thinking-enabled batched prompt overruns the 60s HTTP timeout, so:

```
4 attempts x 60s timeout + (1+2+4)s backoff = 247s, then the request fails
```

versus ~1.5s for the same call without thinking. 247s against the observed 274s.

Worth noting the contrast: the Groq client had always sent `max_tokens: 512, temperature: 0.2`. The Gemini client sent no configuration whatsoever — the asymmetry had simply never been noticed because latency only became visible once batching made prompts large.

**Fix** — Explicit `generationConfig`: `thinkingConfig.thinkingBudget: 0`, `maxOutputTokens`, `temperature`, all configurable (`GEMINI_THINKING_BUDGET`, `GEMINI_MAX_OUTPUT_TOKENS`, `GEMINI_HTTP_TIMEOUT_SECONDS`). Models that reject `thinkingConfig` (2.5 Pro can't fully disable thinking) are detected once and the field is dropped for the rest of the session — degrading to slower calls rather than failing every request.

### 41.2 A silent-empty-description bug found while fixing it

```python
candidates = data.get("candidates", [])
if not candidates:
    return ""
```

An empty string was being returned for a response with no candidates or no parts — which is *precisely* what a thinking-enabled model produces when the output budget is consumed before it writes any answer. That empty string flowed straight into a finding's description, and nothing downstream distinguished it from a real one.

**Fix** — `_extract_text` returns `(text, problem)`. An empty or `MAX_TOKENS`-truncated candidate is retried and then raised as `ProviderUnavailable`, so it degrades *visibly* through the machinery built in entry 38 instead of silently emitting blank prose. Safety blocks are surfaced with their `blockReason`.

### 41.3 Batches were sized by item count only

`batch_size=8` says nothing about prompt size. A Quality summary is one line; a Documentation prompt embeds the symbol's source. Eight of the latter can be tens of thousands of characters — slow to generate against, and likely to hit the output ceiling before all eight sections are written, which makes the response unsplittable and triggers the per-item fallback that costs *more* requests than batching saved.

**Fix** — `chunk_items(items, max_items, max_chars, size_of=...)` caps batches by total prompt size as well as count, used by all three agents. An item larger than the cap on its own still gets sent rather than dropped.

**Verified** — 17 tests in `tests/test_gemini_generation_config.py` asserting the outgoing payload shape, the thinking-rejection downgrade path, that 4xx still fails fast, that empty/truncated/blocked responses raise instead of returning `""`, and that chunking is order-preserving and lossless. Plus a probe reproducing the timeout ladder:

| | HTTP attempts | Outcome | Real-world cost |
|---|---|---|---|
| thinking ON (old default) | 4 | fails | 4 × 60s + 7s = **247s** |
| thinking OFF (new default) | 1 | succeeds | **1.5s** |

Re-ran every earlier probe: health score 84 → 51 → 84, repo scoping intact, security batching still 8× at scale, Flask outage run completes with 57 findings, all interactive bounds hold.

230 backend tests at 91% coverage, 73 frontend tests, clean `tsc -b`.


## 42. Correcting entry 41: the diagnosis didn't apply to the configured model

**Prompt** — "wait, but in my .env I'm using `gemini-3.5-flash-lite`", with the full config pasted.

Entry 41 diagnosed the 270s drafting phase as Gemini 2.5-style thinking being on by default, and fixed it by sending `thinkingConfig.thinkingBudget: 0`. That reasoning was **about the wrong model generation**. Checking the current API docs rather than relying on training knowledge:

- **`gemini-3.5-flash-lite` is real and GA**, and its default thinking level is already **`minimal`** — the lowest setting. There was no thinking overhead to remove, so entry 41's fix could not have produced the improvement it claimed.
- **Gemini 3.x replaced `thinking_budget` with `thinking_level`** (a `minimal`/`low`/`medium`/`high` enum). `thinking_budget` is legacy, and *sending both in one request is a documented 400*.
- **`temperature`, `top_p` and `top_k` are deprecated on 3.x** — currently ignored, documented to return HTTP 400 in future model generations. Entry 41 added `temperature: 0.2` to every request, which on this model is at best dead weight and on a future model is a hard failure.

So entry 41 shipped a payload built for the wrong generation: a legacy thinking field plus a deprecated sampling parameter, aimed at a model that needed neither.

### 42.1 Fix

`GeminiClient` now selects its `generationConfig` by model generation, via a major-version prefix check (`_is_gemini_3_or_newer`) rather than a hardcoded model list — models ship faster than this file changes, and misclassifying a *newer* model as 3.x-style is far milder than sending it deprecated parameters.

| | 2.x | 3.x |
|---|---|---|
| Thinking | `thinkingConfig.thinkingBudget` | `thinking.thinkingLevel` |
| Sampling | `temperature` sent | omitted entirely |

The existing "model rejected the thinking field → drop it and continue" path still applies, and is genuinely safe here: every model's default is sane, and for Flash-Lite it is exactly the `minimal` we would have requested.

### 42.2 The more important change: stop guessing

Three rounds in a row I diagnosed a latency problem by reasoning about what *should* be slow. Twice that was right; this time it wasn't, and there was no way to tell from the evidence available — the pipeline view only shows stage-level durations, from which "many findings", "one slow request", "rate-limited retries" and "batch didn't parse, fell back to per-item" are indistinguishable.

Every agent now times each model call and traces it (`draft.request` / `explain.request`) with `seconds`, `items`, `prompt_chars` and `ok`. These stream live into the Audit page, and `docs/TROUBLESHOOTING.md` maps each pattern to its cause. The next latency question gets answered from data.

**Honest status:** what caused *this particular* 270s is still unknown. It is not thinking (Flash-Lite defaults to minimal). The instrumentation above will identify it on the next run — most likely candidates are free-tier rate limiting (each 429 costs ~7s of backoff) or prompt size.

**Verified** — 35 tests in `tests/test_gemini_generation_config.py`, including parametrised checks that a 3.x model never receives `thinkingConfig` or any sampling parameter, that a 2.x model never receives `thinkingLevel`, that the two thinking fields are mutually exclusive, and that family detection handles `gemini-2.5-flash` through hypothetical `gemini-10-flash`. Confirmed the actual outgoing payload for the reporter's exact model:

```json
{"maxOutputTokens": 4096, "thinking": {"thinkingLevel": "minimal"}}
```

248 backend tests at 91% coverage, 73 frontend tests.

**Sources:** [Using the latest Gemini models](https://ai.google.dev/gemini-api/docs/latest-model), [What's new in Gemini 3.5 Flash](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5), [Gemini 3 Developer Guide](https://ai.google.dev/gemini-api/docs/gemini-3)


## 43. "Repo path does not exist: https://github.com/pallets/flask"

**Prompt** — Two screenshots, both failing at the Repository stage with an error naming a URL that is obviously a valid URL.

The message only appears on the *local filesystem* branch of `resolve_repo`, so the URL had failed `startswith("https://")`. Reproduced immediately:

```
'https://github.com/pallets/flask'   -> would clone
' https://github.com/pallets/flask'  -> FileNotFoundError: Repo path does not exist: ...
'https://github.com/pallets/flask '  -> CalledProcessError (git rejects the trailing space)
```

**A single leading space.** And because HTML collapses leading whitespace, the error banner rendered a perfectly valid-looking URL — the one piece of evidence needed to diagnose it was the one thing the UI couldn't show.

### 43.1 Fixes

- `normalize_source()` strips whitespace and wrapping quotes (a pasted `"https://…"` is a common artefact). Applied in three places — the frontend before sending, a pydantic `field_validator` on `AuditRequest`, and `resolve_repo` itself — because the last of those is also reachable from the CLI.
- `read_repo` and `resolve_repo` had *different* URL tests (`startswith("http")` vs the full prefix list). Both now call one `looks_like_url()`; divergent copies of the same predicate are how "it decided this was a local path" bugs happen.
- The path error now quotes the value (`source!r`), so stray characters are visible, and points at the URL form.
- Clone failures surface git's own stderr instead of a bare exit status, and a missing `git` binary says so explicitly.
- A file passed where a directory is expected now fails with `NotADirectoryError` rather than reading zero files and reporting a clean repo.

### 43.2 A worse bug found underneath

`repo_id_for` normalized with `source.rstrip("/").rstrip(".git")`. **`rstrip` strips characters, not a suffix**, so `.rstrip(".git")` removes any trailing run of `.`, `g`, `i` or `t`:

```
.../pytest  -> .../pytes
.../config  -> .../conf
.../agit    -> .../a
```

Any repository whose name ends in one of those four characters got a mangled id. It happened to be self-consistent, so it never broke visibly — but combined with the whitespace bug it was actively dangerous: ` <url>` and `<url>` hashed differently, so an audit run started from a padded paste would have been recorded as a **different repository**, silently forking one project's history in two and reporting every recurring finding as new.

**Verified** — 39 tests in `tests/test_source_normalization.py`: padded/quoted/tabbed sources normalizing and still being recognised as URLs, local paths not misread as URLs, the padded URL reaching git *trimmed*, clone-failure and missing-git messages, quoting in the path error, and repo-identity equivalence across `url` / `url/` / `url.git` / `url.git/` / padded / quoted. Plus parametrised coverage that `pytest`, `config`, `agit`, `streamlit`, `logging` and `requests` are no longer truncated, and an end-to-end API test asserting two runs from a padded and a bare source land in **one** repository history rather than two.

287 backend tests at 92% coverage, 73 frontend tests, clean `tsc -b`.
