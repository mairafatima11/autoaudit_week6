# User Guide

## Three ways to use AutoAudit AI

### 1. CLI (fastest for a one-off audit)

```bash
python -m autoaudit run <path-or-git-url> --output report.md
```

Examples:

```bash
python -m autoaudit run tests/fixtures/mock_repo --output report.md
python -m autoaudit run /path/to/local/repo --output report.md
python -m autoaudit run https://github.com/psf/requests --output report.md
```

Run it again on the same target and the report tells you what's new, fixed,
and recurring since last time.

### 2. Dashboard (best for exploring results)

1. Start the backend: `uvicorn autoaudit.api.app:app --reload`
2. Start the frontend: `cd frontend && npm run dev`
3. Open `http://localhost:5173`

**Typical flow:**

1. **Dashboard** or **Repository** page — enter a repo path/URL, click
   *Run Audit*.
2. **Audit** page — watch the pipeline execute live (Supervisor →
   Repository → Security → Quality → Documentation → Report), with
   streaming logs underneath.
3. **Findings** page — search/filter by severity, agent, or free text;
   click a finding to see its evidence and description.
4. **Fixes** page — click *Generate Fixes* to have the Fix Agent draft
   patches, PR descriptions, and suggested tests for your top findings.
   **Nothing is ever applied automatically** — copy/download the patch and
   apply it yourself after review.
5. **AI Comparison** page — ask a question and see Groq and Gemini's
   answers side by side, with a merged answer and an agreement indicator.
6. **Memory** page — health-score trend over time, a full repository
   timeline, and a run-vs-run comparison tool (pick any two past runs to
   see what changed).
7. **Reports** page — export the current run as Markdown, HTML, or JSON.
8. **Settings** page — see which model providers are configured and
   whether they're live or in mock mode.

### 3. API (for scripting or integrating into CI)

```bash
curl -X POST http://localhost:8000/api/audits \
  -H "Content-Type: application/json" \
  -d '{"source": "https://github.com/your-org/your-repo"}'
# => {"run_id": "run_...", "status": "running"}

curl http://localhost:8000/api/audits/run_.../status
curl http://localhost:8000/api/audits/run_...              # full report
curl http://localhost:8000/api/audits/run_.../report.md    # markdown export
```

Full interactive reference at `http://localhost:8000/docs`.

## Understanding a finding

Each finding shows:

- **Severity** (high/medium/low/info) and **status** (new/recurring/fixed
  — relative to the last run against the same repo)
- **File and line**, the **rule** that triggered it, and which **agent**
  raised it
- **Description** and, where available, the raw **evidence** (the matched
  code/pattern)

When Security and Quality agents both flag the same or nearby code, the
Supervisor's reconciliation step merges them: you'll see a higher
confidence score and an explicit note if the agents disagreed on severity.

## Understanding the Health Score

A single 0-100 number plus a breakdown by category (security, quality,
documentation, architecture, technical debt, test coverage), computed fresh
from the current run.

**Scores are densities, not counts.** Each category turns its findings into
a weighted penalty *per scanned file*, so the number reflects how much of
the codebase is affected rather than how big the repository is. A 500-file
project with 50 low-severity smells scores far better than a 25-file project
with the same 50 — which is the intent. High-severity findings cost roughly
ten times a low-severity one.

**Findings already fixed don't count against you.** A run compared against
its predecessor also lists issues that were resolved since last time. Those
are shown in the trend and comparison views but excluded from the score and
from the Dashboard's severity tiles, so fixing something can only ever move
the number up.

**Test coverage is a measured signal, not executed line coverage.** AutoAudit
does not run an untrusted repository's test suite. Instead it reads the
repo's own files and reports two observable things: the share of source
modules that have a matching test file or are referenced from the test suite,
and the ratio of test cases to source functions/classes. The Dashboard shows
what was counted underneath the bar. If a repository has no source files to
judge, the category is marked "not measured" and dropped from the composite
rather than scored zero.

See `docs/ARCHITECTURE.md` for the exact weights and half-life constants.

## Mock mode vs. live mode

By default (`AUTOAUDIT_MODE=mock`, the setting in `.env.example`), every
LLM call returns a deterministic, realistic-looking response with zero
network access and zero cost — this is what the test suite and CI use, and
it's a fully functional way to try the whole product without API keys. Set
`AUTOAUDIT_MODE=live` and provide `GROQ_API_KEY` / `GEMINI_API_KEY` to use
real model calls.
