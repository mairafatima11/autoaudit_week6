# AutoAudit AI — Autonomous Software Engineering Reviewer

Points at a repo (local path or `git clone`-able URL), builds a semantic
knowledge base of it, runs a **Supervisor → Worker** multi-agent pipeline
(Security Agent on Groq (Llama 3.3 70B), Quality Agent on Gemini), stores findings in a
persistent audit-history store, and produces a single prioritized,
human-readable report. Run it again on the same repo and it tells you
what's new, what's fixed, and what's recurring.

AutoAudit AI demonstrates a complete multi-agent software engineering review
pipeline combining Retrieval-Augmented Generation (RAG), static analysis,
persistent memory, and LLM reasoning into an end-to-end autonomous code
auditing workflow.

This README covers the full project through **Week 8** of the Phase 3 plan:
the Week 5/6 core pipeline, the Week 7 additions (Supervisor reconciliation,
Fix Agent, Documentation Agent, multi-model routing/validation, caching,
Repository Health Score, a FastAPI layer), and the Week 8 additions (a full
React dashboard, Audit Run Comparison, Docker deployment). See
[`docs/CHECKLIST.md`](docs/CHECKLIST.md) for the itemized final verification
against every internship requirement.

---

## 1. Architecture

```
                         ┌─────────────────────┐
                         │   Supervisor Agent   │
                         │ (orchestrate + log)  │
                         └──────────┬───────────┘
                                    │
                         ┌──────────▼───────────┐
                         │    Tool Registry      │
                         │ (repo reader, Semgrep, │
                         │  Ruff, embeddings)     │
                         └──────────┬───────────┘
                                    │
        ┌───────────────┬──────────┼───────────────┬───────────────┐
        ▼               ▼          ▼               ▼               ▼
 Repository Agent   Security Agent          Quality Agent     Report Agent
 (clone/read repo,  (Groq + Semgrep/      (Gemini +         (merge, dedupe,
  build file map)    pattern scanner)        Ruff +            rank, diff vs
        │                   │                heuristics)       history, render
        │                   │                    │             Markdown)
        ▼                   └─────────┬──────────┘                   │
 Repository Knowledge                 ▼                               │
 Base (RAG): per-file/          Findings (List[Finding])              │
 function embeddings in                │                              │
 a local vector store                  └──────────────┬───────────────┘
        │                                              ▼
        │                                   Persistent Audit Memory
        └──────────────────────────────────►  (SQLite: audit_history.db)
                                              stores every run's findings,
                                              diffs new/fixed/recurring
```

Every agent call and tool call is written to `logs/<run_id>.jsonl` by
`autoaudit/tracing.py` — this is the "hook logging / execution tracing"
primitive from Week 5, and it doubles as an explainable audit trail.

A lightweight `ToolRegistry` maintains the project's available tools
(repository reader, security scanner, linter, embeddings) so the
Supervisor has a single registration point for external capabilities.
This satisfies the Week 5 architecture requirement while keeping the
agent implementations loosely coupled.

### Multi-model routing: provider-agnostic, configurable per agent

**Gemini 2.5 Flash is the primary provider; Groq (Llama 3.3 70B) is the
secondary provider** — both designated explicitly as `PRIMARY_PROVIDER` /
`SECONDARY_PROVIDER` constants in `autoaudit/llm/registry.py`. Neither is
hardcoded into agent logic:

- **`ProviderRegistry`** (`llm/registry.py`) is the single place providers
  are constructed and looked up. Agents never instantiate `GroqClient`/
  `GeminiClient` directly — they call `registry.for_agent("security")`
  and get back whichever provider that agent is configured to use. Adding
  a new provider (OpenRouter, Anthropic, Ollama, ...) is one
  `registry.register(name, factory)` call — zero changes anywhere else.
- **Every agent is independently configurable** via env vars:
  `SECURITY_AGENT_PROVIDER`, `QUALITY_AGENT_PROVIDER`,
  `DOCUMENTATION_AGENT_PROVIDER`, `FIX_AGENT_PROVIDER`. Defaults preserve a
  considered design — Security/Fix agents on Groq (careful, conservative
  reasoning over security-sensitive evidence is worth the cost), Quality/
  Documentation agents on Gemini (higher-volume, lower-stakes reasoning
  across many files, where a faster/cheaper model is the right trade-off)
  — but any of those is a one-line config change, not a code change.
- **Provider health checks + automatic failover**: `LLMClient.health_check()`
  (exposed via `GET /api/models/health`) probes each provider; `ModelRouter`
  retries with exponential backoff and automatically falls back to the
  other provider on error/timeout, and `ProviderRegistry.healthy_provider_order()`
  demotes a provider already known to be unhealthy behind healthy ones.

Both concrete clients share one interface (`autoaudit/llm/base.py`) and
both fall back to a deterministic **mock mode** when no API key is
configured, so the whole pipeline (and the test suite) runs end-to-end
with zero network access and zero cost — this is also how CI/grading can
run it without secrets.

### RAG / Repository Knowledge Base

Instead of re-reading the whole codebase on every run, `repository_agent.py`
chunks each file (roughly per function/class using simple heuristics), the
`embeddings.py` tool turns each chunk into a deterministic hashing-based
vector (no external model download required — this keeps the project fully
offline-runnable; swapping in a real embedding API is a one-line change in
`tools/embeddings.py`), and `memory/vector_store.py` stores vectors in
SQLite and answers nearest-neighbour queries with cosine similarity. Agents
retrieve only the relevant chunks for a given check instead of reasoning
over raw source.

### Persistent Audit Memory

`memory/audit_history.py` is a second SQLite table (`audit_history.db`)
that stores every run's findings keyed by a stable finding fingerprint
(file + line + category + rule). On a second run against the same repo,
`report_agent.py` diffs the new findings against the last run and tags each
one `new`, `fixed`, or `recurring`.

---

## 2. Project Layout

```
autoaudit-ai/
├── README.md
├── prompts.md                 # log of AI interactions used to build this
├── requirements.txt            # runtime deps
├── requirements-dev.txt        # + pytest/coverage/httpx for testing
├── .env.example
├── Dockerfile                  # backend image
├── docker-compose.yml          # api + frontend, wired together
├── docs/                       # architecture diagrams, guides, checklist
├── autoaudit/
│   ├── __init__.py
│   ├── config.py               # env/config loading
│   ├── schemas.py              # pydantic models (Finding, AuditReport, FixProposal, ...)
│   ├── tracing.py              # hook logging / execution tracing
│   ├── cli.py                  # `autoaudit run <repo>` entrypoint
│   ├── llm/
│   │   ├── base.py             # LLMClient interface + mock mode + health_check
│   │   ├── registry.py         # ProviderRegistry — single place providers are built/looked up
│   │   ├── groq_client.py      # secondary provider (precision-focused agents by default)
│   │   ├── gemini_client.py    # primary provider (higher-volume agents by default)
│   │   ├── router.py           # multi-model routing/fallback/retry/compare
│   │   └── validation.py       # Pydantic schema-guard + repair loop
│   ├── tools/
│   │   ├── repo_reader.py      # clone/read repo, file map
│   │   ├── repo_profiler.py    # package manager / framework / directory detection
│   │   ├── static_analysis.py  # Semgrep wrapper + offline fallback scanner
│   │   ├── lint.py             # Ruff wrapper for code-quality checks
│   │   ├── embeddings.py       # chunking + hashing-based embeddings (batch + hybrid-ready)
│   │   ├── cache.py            # file-hash cache: incremental scanning + embedding cache
│   │   ├── github_client.py    # best-effort GitHub REST API metadata enrichment
│   │   └── tool_registry.py    # registers tools for the Supervisor
│   ├── memory/
│   │   ├── vector_store.py     # SQLite-backed repo knowledge base
│   │   └── audit_history.py    # SQLite-backed run history + diffing + comparison
│   ├── analysis/
│   │   ├── health_score.py     # Repository Health Score (0-100 + categories)
│   │   └── run_comparison.py   # Week 8 Audit Run Comparison
│   ├── agents/
│   │   ├── supervisor.py
│   │   ├── repository_agent.py
│   │   ├── security_agent.py
│   │   ├── quality_agent.py
│   │   ├── documentation_agent.py
│   │   ├── fix_agent.py        # proposal-only patch/PR/test generation
│   │   ├── reconciliation.py   # cross-agent agreement/confidence/priority
│   │   └── report_agent.py
│   └── api/
│       ├── app.py              # FastAPI app factory
│       ├── auth.py             # optional API-key auth placeholder middleware
│       ├── jobs.py             # background job runner + progress tracking
│       ├── dependencies.py
│       └── routers/            # audits.py, explorer.py, models.py, repository.py
├── frontend/                   # React + TS + Vite + Tailwind dashboard
│   ├── src/
│   ├── Dockerfile
│   └── nginx.conf
└── tests/
    ├── conftest.py
    ├── fixtures/mock_repo/...   # tiny repo with planted issues
    └── test_*.py                # one file per module, plus API + e2e tests
```

---

## 3. Setup

```bash
cd autoaudit-ai
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # optional: add real API keys here
```

By default (no keys set, or `AUTOAUDIT_MODE=mock`), the pipeline runs fully
offline using deterministic mock LLM responses and the built-in pattern
scanner — this is what the test suite uses. Add `GROQ_API_KEY` /
`GEMINI_API_KEY` to `.env` and set `AUTOAUDIT_MODE=live` to hit the real
APIs. If `semgrep` is installed (`pip install semgrep`) it's used
automatically for the Security Agent's static-analysis pass; otherwise the
built-in fallback scanner is used automatically. Optionally add
`GITHUB_TOKEN` to raise the GitHub metadata API's rate limit (works fine
without one for occasional use — see `docs/DEPLOYMENT.md`).

## 4. Running It

```bash
# Audit the bundled mock repo (fastest way to see it work):
python -m autoaudit run tests/fixtures/mock_repo --output report.md

# Audit any local path:
python -m autoaudit run /path/to/some/repo --output report.md

# Audit a public GitHub repo (clones to a temp dir):
python -m autoaudit run https://github.com/psf/requests --output report.md

# Run it again on the same target to see new/fixed/recurring diffing:
python -m autoaudit run tests/fixtures/mock_repo --output report2.md
```

Each run prints a live progress trace to stdout (Supervisor → Repository
Agent → Security Agent → Quality Agent → Report Agent) and writes:

- `report.md` — the human-readable prioritized report
- `data/vector_store.db` — the repo knowledge base (embeddings)
- `data/audit_history.db` — persistent findings history across runs
- `logs/<run_id>.jsonl` — full execution trace for that run

## 5. Testing

```bash
pip install -r requirements-dev.txt   # runtime deps + pytest/coverage/httpx
python -m pytest tests/ -v
python -m pytest tests/ --cov=autoaudit --cov-report=term-missing
```

Current: **74 tests passing, 90% coverage** (backend + API layer combined).

## 6. Running the API

```bash
uvicorn autoaudit.api.app:app --reload --port 8000
```

Interactive docs at `http://localhost:8000/docs` (Swagger) and `/redoc`. The
CLI and the API both drive the same `Supervisor` — no logic is duplicated
between them.

## 7. Running the Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:5173`, proxying `/api/*` to the backend on port
8000 (configured in `frontend/vite.config.ts`). See
[`frontend/README.md`](frontend/README.md) for the design system and page
list.

## 8. Docker Deployment

```bash
cp .env.example .env      # add real API keys if you want live mode
docker compose up --build
```

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000`

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for production environment
variables, volumes, and troubleshooting.

> **Note:** the Docker configs were written to the standard multi-stage
> Python/Node patterns and validated for YAML/Dockerfile correctness, but
> this sandbox doesn't have a Docker daemon available to actually run
> `docker compose up` end-to-end — if you hit a build issue, please report
> it and I'll fix it directly.

## 8a. Continuous Integration

`.github/workflows/ci.yml` runs on every push/PR to `main`:

- **backend** — `pip install -r requirements-dev.txt`, then `pytest` with
  coverage, failing the build if coverage drops below 80% (currently 90%).
- **frontend** — `oxlint`, `vitest run --coverage` (53 tests), then
  `npm run build`.
- **docker-build-check** — builds both Docker images (doesn't push) as a
  build-sanity gate.

Every command in the backend/frontend jobs was verified locally before
being added to the workflow; the Docker build step itself wasn't (no
Docker daemon in this environment — see the note above).

## 9. Known Limitations (by design)

- Embeddings use a deterministic local hashing-based vectorizer to keep the
  project fully offline-runnable and dependency-light. The embedding
  interface is intentionally abstracted (`tools/embeddings.py`) so a
  production embedding model can be swapped in without changing agent logic.
  ("Deterministic" is now actually true across process restarts, not just
  within one — see `prompts.md` §36 for a real bug that was found and
  fixed here: the hashing trick originally used Python's randomized
  built-in `hash()`, silently breaking cross-restart reproducibility.)
- Static analysis defaults to a small built-in rule set unless `semgrep` is
  installed (the Docker image attempts to install it automatically).
- Test coverage in the Repository Health Score is currently a fixed neutral
  estimate (no coverage tool is wired into the pipeline yet) — documented
  explicitly as an estimate in `analysis/health_score.py`, not a real
  measurement.
- The Interactive Repository Explorer serves file contents from the
  in-memory run context, not disk — this works uniformly for local and
  cloned repos, but means explorer data isn't available for a run after
  the API process restarts (the audit report/findings themselves still
  are, since those are persisted to SQLite).
- GitHub metadata (stars/forks/branch/last commit) is fetched live from
  the GitHub REST API for `github.com` sources — set `GITHUB_TOKEN` to
  raise the rate limit from 60 to 5000 req/hour. Non-GitHub sources (local
  paths, other git hosts) simply don't show this card.
- The repository profiler (`tools/repo_profiler.py`) detects package
  manager and frameworks from lockfiles/manifests and dependency-file
  content already in memory — it's deliberately conservative and won't
  report a framework/package-manager it doesn't have concrete evidence
  for, which means it reports "not detected" for setups that don't follow
  the common conventions it checks (npm/yarn/pnpm/pip/poetry/pipenv/
  cargo/go modules/maven/gradle/bundler/composer + a dozen common
  frameworks).
- No authentication on the frontend, and the API's auth is a minimal
  placeholder (single shared key via `AUTOAUDIT_API_KEY`, off by default) —
  see `docs/DEPLOYMENT.md`. Fine for local/demo use or as a base to build
  real auth on top of; not a production multi-user auth system.

## 10. Documentation

| Doc | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System diagram, sequence diagrams, agent interaction diagram (Mermaid) |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Docker + bare-metal deployment, production env vars |
| [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) | Project conventions, how to add an agent/provider |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | How to use the CLI, dashboard, and API |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Operational procedures |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Troubleshooting + FAQ |
| [`docs/CHECKLIST.md`](docs/CHECKLIST.md) | Itemized final verification against every internship requirement (honest — includes what's *not* done) |
| [`frontend/README.md`](frontend/README.md) | Frontend design system + page list |
