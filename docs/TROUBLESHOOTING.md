# Troubleshooting & FAQ

## Troubleshooting

### `pip install` fails on `numpy` / build tools missing

Use Python 3.11 or 3.12 with a recent pip (`pip install --upgrade pip`
first). The Docker image already includes what's needed.

### Tests fail with SQLite "database is locked"

Usually means two test runs are pointed at the same `AUTOAUDIT_DATA_DIR`
concurrently. Every test in this project uses pytest's `tmp_path` fixture
for isolation — if you added a new test, make sure it does too (see
`docs/DEVELOPER_GUIDE.md`).

### `AUTOAUDIT_MODE=live` but responses still look like mock output

Check that both `AUTOAUDIT_MODE=live` *and* the relevant API key
(`GROQ_API_KEY` / `GEMINI_API_KEY`) are set — `Config.is_live()` requires
mode to be `live`, and each client individually falls back to mock if its
own key is empty even in live mode (see `Config.require_key`).

### Frontend shows "Failed to fetch" everywhere

The dev server proxy (`vite.config.ts`) only forwards `/api/*` to
`http://127.0.0.1:8000` — confirm the backend is actually running on port
8000, or update the proxy target if you're running it elsewhere. In
production (Docker), this is instead nginx's `proxy_pass` in
`frontend/nginx.conf`, pointing at the `api` Compose service by name — that
only resolves inside the Compose network, not from your host machine.

### Cloning a very large / private repo hangs

`repo_reader.py` shells out to `git clone` with no explicit timeout today.
For private repos, ensure the container has SSH keys or a credential
helper configured (not provided out of the box); for very large repos,
prefer auditing a local checkout (`docker-compose.yml`'s `LOCAL_REPO_PATH`
bind mount) over a fresh clone each run.

### Semgrep isn't running / findings look sparser than expected

The Security Agent uses Semgrep if it's installed and falls back to a
built-in pattern scanner otherwise (`tools/static_analysis.py`) — this is
intentional so the project runs with zero external dependencies, but it
does mean fewer rule categories than a full Semgrep ruleset. The Docker
image attempts `pip install semgrep` at build time; check the build logs
if you expect it to be present and it isn't (some platforms don't have
prebuilt Semgrep wheels).

### `docker compose up` fails on the frontend build step

Confirm `frontend/package-lock.json` is committed (the Dockerfile's
`npm install` step expects it to exist for reproducible installs — it
still works without one, just slower/less pinned). If a native dependency
fails to build inside the `node:20-slim` image, check whether it needs a
build-essential-equivalent Debian package added to the Dockerfile.

### "This model is currently experiencing high demand" (HTTP 503) during a run

This is the provider's capacity, **not** your request rate. It is
different from a 429 and has a different fix — see the table in
`docs/ARCHITECTURE.md`.

- **Nothing to tune.** Raising `GEMINI_REQUEST_DELAY_MS` or lowering
  `QUALITY_AGENT_BATCH_SIZE` / `DOCUMENTATION_AGENT_BATCH_SIZE` addresses
  429s and does nothing for a 503: the model is busy for everyone, however
  slowly you ask.
- **The run should not die.** AutoAudit fails over to the secondary
  provider automatically, and if *every* provider is down it completes with
  heuristic descriptions rather than discarding the run. If a 503 aborts a
  run outright, that's a bug — check that both `GEMINI_API_KEY` and
  `GROQ_API_KEY` are set, since failover needs somewhere to fail over to.
- **Check the banner.** A completed-but-degraded run shows how many
  descriptions were placeholders on the Dashboard. Re-running fills them in.

### "quota/rate limit exceeded" (HTTP 429) during a run

This one *is* your request rate, and is worth tuning:

```
GEMINI_REQUEST_DELAY_MS=500        # space requests further apart
QUALITY_AGENT_BATCH_SIZE=12        # fewer, larger requests
DOCUMENTATION_AGENT_BATCH_SIZE=12
GEMINI_MAX_RETRIES=5               # more patient backoff
```

Free-tier keys have per-minute limits low enough that a large repository
will hit them; the settings above trade wall-clock time for headroom.

### "Repo path does not exist: https://github.com/..."

The URL is being treated as a local filesystem path, which happens when it
doesn't start with `https://` — almost always **stray whitespace from a
paste**. A single leading space is enough, and HTML collapses it, so the
error banner renders a URL that looks perfectly correct.

Sources are now normalized (whitespace and wrapping quotes stripped) in the
frontend, at the API boundary, and in `resolve_repo` itself, so this
shouldn't recur. If you do see a path error, it's quoted (`'...'`) to make
any remaining stray characters visible.

This mattered beyond the crash: `repo_id` is derived from the source
string, so ` https://…/flask` and `https://…/flask` hashed differently and
would have split one repository's audit history into two unrelated
timelines.

### Quality or Docs drafting takes minutes on a small repository

**Read the trace first — don't guess.** Every model call is logged to
`logs/<run_id>.jsonl` as a `draft.request` (or `explain.request`) event
carrying `seconds`, `items`, `prompt_chars` and `ok`. These also stream live
into the Audit page. Four very different causes look identical from the
stage timer alone:

| What the events show | Cause |
|---|---|
| many `draft.request`, each fast | just a lot of findings — raise the batch size |
| few events, each very slow | model latency — check the thinking level |
| `ok=false` then a burst of single-item requests | batch response didn't parse; it fell back per item |
| `provider_unavailable` with multi-second gaps | rate limiting — see the 429 section |

**Thinking level.** Gemini's reasoning setting depends on the model
generation, and the wrong one is either ignored or an error:

- **Gemini 2.x** — `GEMINI_THINKING_BUDGET` (integer). 2.5 Flash thinks by
  default; `0` disables it.
- **Gemini 3.x** — `GEMINI_THINKING_LEVEL` (`minimal`/`low`/`medium`/`high`).
  Defaults vary per model: `gemini-3.5-flash-lite` already defaults to
  `minimal`, so there is no thinking overhead to remove there, and raising
  the level is the thing that would *cause* latency.

AutoAudit sends only the pair valid for your configured `GEMINI_MODEL`.

Related settings when a batch is slow or comes back unusable:

- `GEMINI_MAX_OUTPUT_TOKENS` (default 4096) — if a batched response is
  truncated it can't be split back apart, and the agent falls back to one
  request per item, costing *more* than batching saved. A truncated
  response is reported explicitly rather than returning empty text.
- Batches are capped by total prompt size as well as item count
  (`DEFAULT_MAX_BATCH_CHARS`), because documentation prompts embed source
  code and eight of them can be enormous.

### The Security stage runs for minutes and everything else waits

Check `logs/<run_id>.jsonl` for the `security_agent / static_analysis.done`
event — it records both the finding `count` and the `seconds` the scan took.
Two different things look the same from the pipeline view:

- **Semgrep itself is slow.** `semgrep --config=auto` downloads rule packs
  over the network and can take minutes on a large repository. The `seconds`
  field tells you if this is where the time went. Uninstalling Semgrep falls
  back to the built-in offline scanner (far faster, far fewer findings).
- **Explaining the findings is slow.** Semgrep can return hundreds of
  findings where the fallback scanner returns a handful. Explanations are
  batched (`SECURITY_AGENT_BATCH_SIZE`, default 8), so cost scales with
  `ceil(N / 8)` requests — raise the batch size to trade per-request size
  for fewer round trips.

Security's model calls no longer run in the parallel detection phase, so
they can't block Quality and Documentation. If the pipeline view shows
Security spinning while everything behind it sits idle, that's a bug.

### "Generate Fixes" or "Run Comparison" spins for minutes

Both are bounded now and should never spin indefinitely:

- **Fix proposals** share a 90s wall-clock budget across the batch and draft
  concurrently. You always get one proposal per finding; any that couldn't
  be drafted in time arrive as a clearly-labelled "manual review required"
  proposal rather than being dropped.
- **Model comparison** runs on the 45s interactive budget covering all
  retries and failover, then renders whatever each provider returned —
  including per-provider errors.
- The **browser** aborts either request after 120s and shows a readable
  timeout message. Both spinners display elapsed seconds and warn once the
  wait is longer than normal.

If a wait is still unexpectedly long, it's almost always a rate-limited
provider. Check `logs/<run_id>.jsonl` for `propose.provider_unavailable`
events, and see the 429 guidance above.

To tune the bounds, adjust `RouterConfig.interactive_timeout_seconds` and
`fix_agent.DEFAULT_BATCH_BUDGET_SECONDS`. Keep the frontend's
`LONG_TIMEOUT_MS` (`frontend/src/lib/api.ts`) comfortably above both, so the
server's specific error wins the race against the client's generic one.

## FAQ

**Does AutoAudit AI ever modify my code automatically?**
No. The Fix Agent only ever produces a `FixProposal` (patch text, PR
description, suggested tests) for you to review and apply yourself — this
is a hard rule enforced by design (the class has no write/apply/commit
method at all — see `tests/test_week7_features.py::test_fix_agent_never_writes_to_disk`).

**Can I use a different model provider than Groq/Gemini?**
Yes — see "Adding a new LLM provider" in `docs/DEVELOPER_GUIDE.md`. The
`LLMClient` interface and `ModelRouter` are provider-agnostic.

**Why SQLite instead of Postgres/a hosted vector DB?**
Keeps the whole project runnable with zero external services — clone it,
`pip install`, and it works. See "Scaling notes" in `docs/DEPLOYMENT.md`
for what would change to support networked storage.

**Does it work without any API keys at all?**
Yes — `AUTOAUDIT_MODE=mock` (the default) runs the entire pipeline,
including the Fix and Documentation agents, with deterministic mock
responses. This is what the automated test suite uses.

**How is "confidence" calculated?**
For reconciled findings, from severity plus cross-agent agreement (see
`agents/reconciliation.py`). For model comparison / Fix Agent output in
live mode, from a length-based heuristic when a provider doesn't return
its own confidence signal (see `_estimate_confidence` in `llm/router.py`)
— documented there as a heuristic, not a calibrated probability.

**What happens if a model returns malformed output?**
It's never allowed into the pipeline. `llm/validation.py` re-prompts the
model with the validation error (repair loop), then tries a fallback
model, then raises a clear `ValidationFailure` if both fail — callers like
the Fix Agent catch that and substitute a clearly-labeled deterministic
fallback rather than passing bad data through.
