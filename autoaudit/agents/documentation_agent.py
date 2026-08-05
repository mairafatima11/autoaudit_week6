"""Documentation Agent (Week 7): detects missing docstrings, missing
README sections, missing inline comments on non-trivial logic, and missing
API documentation, then drafts suggested documentation for each gap.

This is the single place missing-docstring/missing-API-doc detection
happens — QualityAgent deliberately does not duplicate it under
Category.QUALITY (see quality_agent.py's module docstring).

Detection is heuristic (deterministic, cheap, works offline). Drafting the
actual suggested text goes through the model router so it benefits from
routing/fallback like the other agents.

Drafting previously made one live Gemini request per gap (per missing
docstring, per missing comment, per missing API doc, per missing README
section). Combined with the Quality Agent hitting the same shared Gemini
client concurrently, that burst of tiny requests was enough to trip the
API's rate limit (HTTP 429) even though a single one-off request against
the same key succeeded fine. Gaps are now collected first, then drafted in
configurable batches (`batch_size` — see Config.documentation_agent_batch_size
/ DOCUMENTATION_AGENT_BATCH_SIZE) with one request per batch instead of one
per gap, falling back to per-item requests only if a batch response can't
be cleanly parsed back apart. Mock mode is unaffected: it has no network
cost, so it keeps drafting one item at a time.

Detection and drafting are also split into their own `detect()` / `draft()`
methods, rather than only living inside `run()`. This lets the supervisor
run `detect()` for this agent concurrently with Security and Quality's own
detection passes, then run the LLM-bound `draft()` steps for Quality and
Documentation sequentially afterwards — so the two agents' Gemini requests
don't land in the same burst and trip 429s. `run()` is kept as a
`detect()` + `draft()` wrapper for anyone calling it directly.

**Provider failover.** Batching, spacing and retry all address HTTP 429 —
*our* quota, which we control by asking less often. They do nothing for a
503 UNAVAILABLE ("this model is currently experiencing high demand"), which
is the provider's own capacity and is identical however politely we ask.
The only real remedy there is a different provider. This agent used to
resolve `self.router.clients[self.provider]` and call that raw client
directly, which bypassed `ModelRouter` entirely — so despite the module
docstring above promising routing/fallback, a Gemini 503 killed the run
outright while a perfectly healthy Groq provider sat idle. Drafting now
goes through `router.complete_text()`, which fails over automatically.

**Degradation instead of collapse.** A drafting failure no longer aborts
the audit. Documentation suggestions are the *last* step of a run that may
already have spent several minutes on repository indexing, security and
quality analysis; throwing all of that away because a text-generation call
failed is a bad trade. A gap that can't be drafted keeps its detected
location and rationale and carries a clear placeholder instead of prose,
and the count of degraded suggestions is traced and reported.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from ..llm.base import mock_hash_summary
from ..llm.batching import build_batch_prompt, chunk_items, split_batch_response
from ..llm.router import ModelRouter
from ..schemas import DocGapKind, DocSuggestion
from ..tools.repo_reader import FileRecord
from ..tracing import Tracer

SYSTEM_PROMPT = (
    "You are a technical writer helping engineers document their code. Given a "
    "code symbol or section lacking documentation, write a concise, accurate "
    "docstring or comment in the appropriate style for the language. Do not "
    "invent behavior you cannot infer from the given code."
)

BATCH_INSTRUCTIONS = (
    "You are a technical writer helping engineers document their code. Below "
    "are several independent documentation requests, each in its own numbered "
    "item. For each one, write a concise, accurate docstring/comment/section "
    "in the appropriate style. Do not invent behavior you cannot infer from "
    "the given code."
)

ARCHITECTURE_SYSTEM_PROMPT = (
    "You are a senior engineer writing a brief architecture overview for a "
    "codebase, based only on its directory/module structure. Describe the "
    "apparent organization (layers, modules, entry points) in 3-6 sentences. "
    "Do not invent frameworks, libraries, or behavior you cannot infer from "
    "the file list given — if it's ambiguous, say so plainly rather than "
    "guessing."
)

_PY_DEF_RE = re.compile(r"^(def|class)\s+(\w+)")
README_EXPECTED_SECTIONS = ["installation", "usage", "configuration", "testing", "license"]

DEFAULT_BATCH_SIZE = 8


@dataclass
class _PendingSuggestion:
    """A DocSuggestion whose Gemini-drafted text hasn't been filled in
    yet — everything else needed, plus the prompt used to draft it."""

    prompt: str
    file: str
    line: int
    kind: DocGapKind
    symbol: str
    rationale: str


class DocumentationAgent:
    def __init__(
        self,
        router: ModelRouter,
        tracer: Tracer,
        provider: str = "gemini",
        batch_size: int = DEFAULT_BATCH_SIZE,
        include_tests: bool = False,
        skip_generated_migrations: bool = True,
    ) -> None:
        self.router = router
        self.tracer = tracer
        self.provider = provider
        self.batch_size = max(1, batch_size)
        # Off by default: test helpers/fixtures are conventionally
        # undocumented in most Python codebases, so scanning tests/ for
        # missing docstrings mostly produces noise (e.g. a pytest fixture
        # like `client(app)` flagged the same way as an undocumented
        # public API function) rather than actionable gaps. Set to True
        # for codebases that do expect docstrings on test code.
        self.include_tests = include_tests
        # On by default: alembic/versions/*.py files are generated by
        # `alembic revision` and contain boilerplate upgrade()/downgrade()
        # functions that are essentially never hand-documented in real
        # projects — flagging them just adds noise without an actionable
        # fix.
        self.skip_generated_migrations = skip_generated_migrations
        # Number of suggestions in the last `draft()` that fell back to a
        # placeholder because every provider was unavailable. Surfaced by
        # the Supervisor so a degraded run is visible rather than silent.
        self.degraded_count = 0

    # ---- exclusions ----------------------------------------------------

    def _is_excluded_path(self, path: str) -> bool:
        """Paths this agent should skip for docstring/API-doc gap
        detection, based on configurable, path-pattern rules rather than
        hardcoded per-repo filenames — so this generalizes across
        differently-structured target repos instead of only working for
        one project's naming conventions."""
        normalized = path.replace("\\", "/")

        if self.skip_generated_migrations and "alembic/versions/" in normalized:
            return True

        if not self.include_tests:
            basename = normalized.rsplit("/", 1)[-1]
            if normalized.startswith("tests/") or "/tests/" in normalized:
                return True
            if basename.startswith("test_") and basename.endswith(".py"):
                return True
            if basename == "conftest.py":
                return True

        return False

    # ---- detection ---------------------------------------------------

    def _detect_missing_docstrings(self, files: list[FileRecord]) -> list[tuple[str, int, str, str]]:
        """Returns (file, line, symbol_signature, code_context) tuples."""
        gaps = []
        for rec in files:
            if rec.language != "python":
                continue
            if self._is_excluded_path(rec.path):
                continue
            self.tracer.log("documentation_agent", "processing_file", file=rec.path)
            for chunk in rec.chunks:
                stripped = chunk.text.lstrip()
                match = _PY_DEF_RE.match(stripped)
                if not match:
                    continue
                symbol = match.group(2)
                if symbol.startswith("_"):
                    continue
                body_lines = chunk.text.splitlines()[1:4]
                has_doc = any('"""' in ln or "'''" in ln for ln in body_lines)
                if has_doc:
                    continue
                signature = chunk.text.splitlines()[0].strip()
                gaps.append((rec.path, chunk.start_line, signature, chunk.text[:400]))
        return gaps

    def _detect_missing_comments(self, files: list[FileRecord]) -> list[tuple[str, int, str, str]]:
        """Flags long, branch-heavy functions with zero inline comments —
        a proxy for 'non-trivial logic with no explanation'."""
        gaps = []
        for rec in files:
            if rec.language != "python":
                continue
            for chunk in rec.chunks:
                lines = chunk.text.splitlines()
                n_lines = len(lines)
                branch_count = sum(1 for ln in lines if ln.strip().startswith(("if ", "elif ", "for ", "while ", "try:", "except")))
                has_comment = any(ln.strip().startswith("#") for ln in lines)
                if n_lines >= 15 and branch_count >= 3 and not has_comment:
                    gaps.append((rec.path, chunk.start_line, lines[0].strip(), chunk.text[:400]))
        return gaps

    def _detect_missing_readme_sections(self, readme_text: str) -> list[str]:
        lowered = readme_text.lower()
        return [s for s in README_EXPECTED_SECTIONS if s not in lowered]

    def _detect_missing_api_docs(self, files: list[FileRecord]) -> list[tuple[str, int, str, str]]:
        """Public functions in files that look like API/route modules but
        have no docstring — separate from the general docstring check so
        it can be surfaced as its own gap kind for API-consumer-facing
        code."""
        gaps = []
        api_hint_re = re.compile(r"@app\.(get|post|put|delete|patch)|@router\.(get|post|put|delete|patch)")
        for rec in files:
            if rec.language != "python":
                continue
            if self._is_excluded_path(rec.path):
                continue
            if not api_hint_re.search(rec.content):
                continue
            for chunk in rec.chunks:
                stripped = chunk.text.lstrip()
                if not stripped.startswith("def ") and not stripped.startswith("async def "):
                    continue
                body_lines = chunk.text.splitlines()[1:4]
                if any('"""' in ln for ln in body_lines):
                    continue
                gaps.append((rec.path, chunk.start_line, chunk.text.splitlines()[0].strip(), chunk.text[:400]))
        return gaps

    # ---- generation ----------------------------------------------------

    def _resolve_client(self):
        """The configured client, used only for mock-mode detection and the
        one-off architecture explanation. Drafting must go through
        `self.router` (see `_complete`) so provider failover applies."""
        return self.router.clients.get(self.provider) or next(iter(self.router.clients.values()))

    def _complete(self, prompt: str, items: int = 1) -> str | None:
        """One routed completion. Returns None when *every* provider failed,
        so callers can degrade instead of propagating an exception that
        would destroy the whole audit run.

        Timed and traced per request — see QualityAgent._complete."""
        started = time.monotonic()
        text, error = self.router.complete_text(
            prompt, system=SYSTEM_PROMPT, profile="cheap", provider=self.provider
        )
        elapsed = round(time.monotonic() - started, 2)
        self.tracer.log(
            "documentation_agent", "draft.request",
            seconds=elapsed, items=items, prompt_chars=len(prompt), ok=error is None,
        )
        if error is not None:
            self.tracer.log(
                "documentation_agent", "draft.provider_unavailable",
                error=error[:300], seconds=elapsed,
            )
            return None
        return text

    @staticmethod
    def _placeholder(reason: str = "all configured model providers were unavailable") -> str:
        return (
            f"[not drafted — {reason}. The gap itself was detected reliably "
            f"(no model needed for that); re-run the audit to generate suggested text.]"
        )

    def _draft_batch(self, prompts: list[str]) -> list[str]:
        """Draft all `prompts`, batching live requests `self.batch_size` at
        a time. Mock mode drafts one at a time (no network cost, and keeps
        deterministic per-item output)."""
        self.degraded_count = 0
        if not prompts:
            return []
        if getattr(self._resolve_client(), "mock", False):
            return [f"[suggested] {mock_hash_summary(p, max_len=200)}" for p in prompts]

        results: list[str] = []
        # Size-aware: documentation prompts embed the symbol's source, so a
        # fixed count of 8 can build an enormous prompt. See `chunk_items`.
        for batch in chunk_items(prompts, self.batch_size):
            results.extend(self._draft_one_batch(batch))
        if self.degraded_count:
            self.tracer.log(
                "documentation_agent", "draft.degraded",
                degraded=self.degraded_count, total=len(prompts),
            )
        return results

    def _draft_one_batch(self, batch: list[str]) -> list[str]:
        if len(batch) == 1:
            text = self._complete(batch[0])
            if text is None:
                self.degraded_count += 1
                return [self._placeholder()]
            return [text]

        response = self._complete(build_batch_prompt(batch, BATCH_INSTRUCTIONS), items=len(batch))

        if response is None:
            # Every provider refused the batch. Retrying the same batch one
            # item at a time would mean N more full retry/backoff cycles
            # against endpoints that just told us they can't serve us — for
            # a repo like Flask that's hundreds of doomed requests and many
            # minutes. Degrade the whole batch at once instead.
            self.degraded_count += len(batch)
            return [self._placeholder()] * len(batch)

        parsed = split_batch_response(response, len(batch))
        if parsed is not None:
            return parsed

        # The call succeeded but the response couldn't be split apart. Here
        # per-item retries *are* worth it — the provider is demonstrably
        # up, and a smaller prompt is more likely to come back cleanly.
        self.tracer.log("documentation_agent", "batch_parse_failed", batch_size=len(batch))
        out: list[str] = []
        for item in batch:
            text = self._complete(item)
            if text is None:
                self.degraded_count += 1
                out.append(self._placeholder())
            else:
                out.append(text)
        return out

    # ---- architecture explanation --------------------------------------

    @staticmethod
    def _build_module_summary(files: list[FileRecord]) -> str:
        """Deterministic structural digest of the repo (directories, file
        counts per directory, languages present, apparent entry points) —
        the actual input the architecture explanation is grounded in, so
        the model can't invent structure that isn't there."""
        by_dir: dict[str, list[str]] = {}
        languages: dict[str, int] = {}
        entry_point_hints = []
        for rec in files:
            directory = rec.path.rsplit("/", 1)[0] if "/" in rec.path else "(root)"
            by_dir.setdefault(directory, []).append(rec.path.rsplit("/", 1)[-1])
            languages[rec.language] = languages.get(rec.language, 0) + 1
            base = rec.path.rsplit("/", 1)[-1]
            if base in ("main.py", "app.py", "__main__.py", "index.ts", "index.js", "server.py", "cli.py"):
                entry_point_hints.append(rec.path)

        lines = [f"Total files: {len(files)}", f"Languages: {dict(sorted(languages.items(), key=lambda kv: -kv[1]))}"]
        if entry_point_hints:
            lines.append(f"Likely entry points: {', '.join(entry_point_hints[:5])}")
        lines.append("Directory structure:")
        for directory, filenames in sorted(by_dir.items()):
            shown = ", ".join(sorted(filenames)[:8])
            more = f" (+{len(filenames) - 8} more)" if len(filenames) > 8 else ""
            lines.append(f"  {directory}/ [{len(filenames)} files]: {shown}{more}")
        return "\n".join(lines)

    def generate_architecture_explanation(self, files: list[FileRecord]) -> str:
        """Whole-repo architecture summary — separate from the per-symbol
        doc suggestions above, since it's one explanation for the report
        as a whole rather than a per-file gap. Always a single request
        (there's only ever one per run), so it isn't batched."""
        if not files:
            return "No files were available to analyze."
        summary = self._build_module_summary(files)
        prompt = f"Repository structure:\n{summary}\n\nWrite the architecture overview."
        client = self._resolve_client()
        if getattr(client, "mock", False):
            top_dirs = sorted({f.path.rsplit("/", 1)[0] if "/" in f.path else "(root)" for f in files})
            return (
                f"[mock] This repository contains {len(files)} scanned file(s) across "
                f"{len(top_dirs)} directory grouping(s) ({', '.join(top_dirs[:5])}"
                f"{'...' if len(top_dirs) > 5 else ''}). Structural summary only — "
                f"connect a live model for a narrative architecture explanation."
            )
        text, error = self.router.complete_text(
            prompt, system=ARCHITECTURE_SYSTEM_PROMPT, profile="cheap", provider=self.provider
        )
        if error is not None:
            # Degrade to the deterministic structural digest rather than
            # aborting the run at its final step over one prose paragraph.
            self.tracer.log("documentation_agent", "architecture.provider_unavailable", error=error[:300])
            return (
                f"[Architecture narrative unavailable — all configured model providers "
                f"failed. Structural summary follows.]\n\n{summary}"
            )
        return text or ""

    def detect(self, files: list[FileRecord], readme_text: str = "") -> list[_PendingSuggestion]:
        """Heuristic pass only — no LLM calls. Returns gaps pending a
        Gemini-drafted suggestion, so callers can run this concurrently
        with other agents' own detection passes and defer the LLM-bound
        `draft()` step until afterwards (see supervisor.py)."""
        self.tracer.log("documentation_agent", "scan.start", files=len(files))

        pending: list[_PendingSuggestion] = []

        for file, line, signature, context in self._detect_missing_docstrings(files):
            pending.append(
                _PendingSuggestion(
                    prompt=f"Write a docstring for:\n{context}",
                    file=file, line=line, kind=DocGapKind.MISSING_DOCSTRING,
                    symbol=signature, rationale="Public symbol has no docstring.",
                )
            )

        for file, line, signature, context in self._detect_missing_comments(files):
            pending.append(
                _PendingSuggestion(
                    prompt=f"Write a brief explanatory comment for this branch-heavy code:\n{context}",
                    file=file, line=line, kind=DocGapKind.MISSING_COMMENT,
                    symbol=signature, rationale="Non-trivial control flow with no inline comments.",
                )
            )

        for file, line, signature, context in self._detect_missing_api_docs(files):
            pending.append(
                _PendingSuggestion(
                    prompt=f"Write API documentation (purpose, params, response) for this endpoint handler:\n{context}",
                    file=file, line=line, kind=DocGapKind.MISSING_API_DOC,
                    symbol=signature, rationale="Route handler exposed without API documentation.",
                )
            )

        for section in self._detect_missing_readme_sections(readme_text):
            pending.append(
                _PendingSuggestion(
                    prompt=f"Draft a '{section.title()}' section for a project README, given this existing README:\n{readme_text[:600]}",
                    file="README.md", line=0, kind=DocGapKind.MISSING_README_SECTION,
                    symbol=section, rationale=f"README has no '{section}' section.",
                )
            )

        self.tracer.log("documentation_agent", "detect.done", pending=len(pending))
        return pending

    def draft(self, pending: list[_PendingSuggestion]) -> list[DocSuggestion]:
        """Drafts each pending gap via (batched) Gemini requests and
        assembles the final DocSuggestion objects."""
        drafts = self._draft_batch([p.prompt for p in pending])

        suggestions = [
            DocSuggestion(
                file=p.file, line=p.line, kind=p.kind,
                symbol=p.symbol, suggestion=draft, rationale=p.rationale,
            )
            for p, draft in zip(pending, drafts)
        ]

        self.tracer.log("documentation_agent", "scan.done", suggestions=len(suggestions))
        return suggestions

    def run(self, files: list[FileRecord], readme_text: str = "") -> list[DocSuggestion]:
        """Backward-compatible wrapper: detect() then draft()."""
        pending = self.detect(files, readme_text=readme_text)
        return self.draft(pending)