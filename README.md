# AutoAudit AI — Autonomous Software Engineering Reviewer

Points at a repo (local path or `git clone`-able URL), builds a semantic
knowledge base of it, runs a **Supervisor → Worker** multi-agent pipeline
(Security Agent on Claude, Quality Agent on Gemini), stores findings in a
persistent audit-history store, and produces a single prioritized,
human-readable report. Run it again on the same repo and it tells you
what's new, what's fixed, and what's recurring.

AutoAudit AI demonstrates a complete multi-agent software engineering review
pipeline combining Retrieval-Augmented Generation (RAG), static analysis,
persistent memory, and LLM reasoning into an end-to-end autonomous code
auditing workflow.

This README covers everything built through **Week 6** of the Phase 3 plan
(Week 5-second-half scaffold + Week 6 core features). Week 7/8 items
(Supervisor reconciliation/confidence scoring, Fix Agent, Documentation
Agent, deployment, final polish) are **out of scope for this drop** and will
be added on request.

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
 (clone/read repo,  (Claude + Semgrep/      (Gemini +         (merge, dedupe,
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

### Why two LLM providers, not one task split arbitrarily

- **Claude (Security Agent)** — used where judgment/precision matters:
  interpreting static-analysis evidence (hardcoded secrets, injection
  patterns) into human-readable, context-aware findings. Careful,
  conservative reasoning is worth the extra cost here.
- **Quality Agent (Gemini + Ruff + heuristics)** — performs static
  code-quality analysis using Ruff when available, supplemented by
  heuristic checks (duplicate code, long functions, missing docstrings).
  Gemini converts raw lint results into concise, human-readable
  recommendations. This higher-volume, lower-stakes reasoning across many
  files is where a cheaper/faster model is the right trade-off.

Both clients share one interface (`autoaudit/llm/base.py`) so a provider can
be swapped without touching agent code, and both fall back to a
deterministic **mock mode** when no API key is configured, so the whole
pipeline (and the test suite) runs end-to-end with zero network access and
zero cost. This is also how CI/grading can run it without secrets.

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
├── requirements.txt
├── .env.example
├── autoaudit/
│   ├── __init__.py
│   ├── config.py               # env/config loading
│   ├── schemas.py              # pydantic models (Finding, AuditReport, ...)
│   ├── tracing.py              # hook logging / execution tracing
│   ├── cli.py                  # `autoaudit run <repo>` entrypoint
│   ├── llm/
│   │   ├── base.py             # LLMClient interface + mock mode
│   │   ├── claude_client.py    # Security Agent's model
│   │   └── gemini_client.py    # Quality Agent's model
│   ├── tools/
│   │   ├── repo_reader.py      # clone/read repo, file map
│   │   ├── static_analysis.py  # Semgrep wrapper + offline fallback scanner
│   │   ├── lint.py             # Ruff wrapper for code-quality checks
│   │   ├── embeddings.py       # chunking + hashing-based embeddings
│   │   └── tool_registry.py    # registers tools for the Supervisor
│   ├── memory/
│   │   ├── vector_store.py     # SQLite-backed repo knowledge base
│   │   └── audit_history.py    # SQLite-backed run history + diffing
│   └── agents/
│       ├── supervisor.py
│       ├── repository_agent.py
│       ├── security_agent.py
│       ├── quality_agent.py
│       └── report_agent.py
└── tests/
    ├── conftest.py
    ├── fixtures/mock_repo/...   # tiny repo with planted issues
    └── test_*.py                # one file per module + one e2e test
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
scanner — this is what the test suite uses. Add `ANTHROPIC_API_KEY` /
`GEMINI_API_KEY` to `.env` and set `AUTOAUDIT_MODE=live` to hit the real
APIs. If `semgrep` is installed (`pip install semgrep`) it's used
automatically for the Security Agent's static-analysis pass; otherwise the
built-in fallback scanner is used automatically.

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
pip install -r requirements.txt      # includes pytest, pytest-cov
python -m pytest tests/ -v
python -m pytest tests/ --cov=autoaudit --cov-report=term-missing
```
## 6. Known Limitations (by design, at this milestone)

- No Fix Agent or Documentation Agent yet — Week 7 scope.
- Embeddings currently use a deterministic local hashing-based vectorizer
  to keep the project fully offline and dependency-light. The embedding
  interface is intentionally abstracted so a production embedding model
  (e.g., OpenAI or Sentence Transformers) can be integrated later without
  changing agent logic.
- No web dashboard yet — CLI + Markdown report only, per the proposal's
  risk mitigation ("default to CLI + Markdown, add dashboard only if the
  core pipeline is solid ahead of schedule").
- Static analysis defaults to a small built-in rule set unless `semgrep` is
  installed on the machine.
