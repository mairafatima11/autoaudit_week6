# Developer Guide

## Local setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # AUTOAUDIT_MODE=mock works with no keys
python -m pytest -v
```

Frontend:

```bash
cd frontend && npm install && npm run dev
```

## Project conventions

- **Every agent is a plain class** with a `run(...)` method that returns
  Pydantic models from `schemas.py` — no shared mutable state, no global
  singletons inside agents themselves (only the API layer's `Supervisor`
  instance is a process-wide singleton, and only for `_run_contexts`).
- **Every LLM client implements `LLMClient`** (`llm/base.py`): one
  `complete(prompt, system=None) -> str` method, a `provider` class
  attribute, and a `mock` flag that returns deterministic output with zero
  network calls. This is what makes the whole pipeline and every test
  offline-runnable.
- **Every structured LLM output goes through a Pydantic schema.** If you're
  adding an agent that asks a model for structured data, add the schema to
  `schemas.py` first, then use `llm/validation.py`'s `validate_with_repair`
  to parse/validate/repair the model's response — never trust raw JSON
  parsing without a schema guard.
- **Tracer everything.** Call `tracer.log(actor, event, **fields)` at the
  start/end of any agent step. The API's live progress view and streaming
  logs are derived entirely from these trace events — there's no separate
  event system to keep in sync.

## Adding a new agent

1. Add any new output schema(s) to `schemas.py`.
2. Create `autoaudit/agents/your_agent.py` with a `run(...)` method,
   accepting a `Tracer` and whatever inputs it needs (LLM client or
   `ModelRouter`, `VectorStore`, file records, etc).
3. Wire it into `Supervisor.run()` in `agents/supervisor.py` — call it in
   the right pipeline position, log a `tracer.log(...)` before/after, and
   attach its output to the `AuditReport` (add a field to `AuditReport` in
   `schemas.py` if it needs to be part of the persisted report shape).
4. If the frontend needs to see live progress for it, add it to
   `PIPELINE_STAGES` in `api/jobs.py` and to `AGENT_LABELS` in
   `frontend/src/components/PipelineRail.tsx`.
5. Write a mock-mode test (see `tests/test_week7_features.py` for the
   pattern: build the agent with mock clients, assert on the shape and
   invariants of its output, not on exact LLM text).

## Adding a new LLM provider

1. Create `autoaudit/llm/your_client.py` implementing `LLMClient`
   (`provider` attribute, `complete()`, a `mock` flag with a deterministic
   mock response — see `groq_client.py` / `gemini_client.py`). The base
   class's default `health_check()` (a timed trivial `complete()` call) is
   usually fine as-is; override it only if the provider has a cheaper
   dedicated health-check endpoint.
2. Add its API key/model env vars to `Config` (`config.py`) and
   `.env.example`.
3. Register it in `ProviderRegistry.__init__` (`llm/registry.py`) — this
   is the **only** place a provider is constructed. Nothing in
   `supervisor.py`, `api/routers/models.py`, or any agent needs to change;
   they all go through `registry.get(name)` / `registry.for_agent(name)`.
   (To add a provider at runtime instead of at registry-construction time,
   e.g. from a plugin, call `registry.register(name, factory)`.)
4. If an agent should default to the new provider, change that agent's
   `<agent>_agent_provider` default in `Config`, or just set the
   corresponding env var — no code change needed for a per-deployment
   override.

## Running just the parts you're working on

```bash
python -m pytest tests/test_week7_features.py -v      # new agents
python -m pytest tests/test_api.py -v                   # API layer
python -m autoaudit run tests/fixtures/mock_repo -o /tmp/r.md   # full CLI e2e
uvicorn autoaudit.api.app:app --reload                   # API, hot reload
```

## Frontend conventions

- All server state goes through TanStack React Query (`src/lib/api.ts`) —
  no manual `useEffect` + `fetch` + `useState` juggling.
- Design tokens live in `src/index.css` under `@theme` — add new
  colors/fonts there, not as one-off hex values in components.
- Small, composable UI primitives live in `src/components/ui/`; feature
  components (PipelineRail, HealthGauge, FindingCard) live directly under
  `src/components/`.
- Every async view needs, at minimum: a loading state (`Skeleton`), an
  empty state (`EmptyState`), and — for mutations — a visible error state.
