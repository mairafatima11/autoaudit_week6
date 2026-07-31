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
- Claude interpretation of findings

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