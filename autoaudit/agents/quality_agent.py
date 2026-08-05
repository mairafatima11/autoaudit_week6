"""Quality Agent: flags code smells (long functions, near-duplicate code
blocks) via simple heuristics plus vector-similarity retrieval, then uses
Gemini to phrase each as a finding. Runs on a second model deliberately, so
its output can later be cross-checked against the Security Agent's
(Week 7 reconciliation scope).

Missing-docstring detection intentionally lives in DocumentationAgent only
(Category.DOCS), not here. It used to also run here as a Category.QUALITY
finding, which meant every missing docstring was reported twice by two
different agents under two different categories — the Quality score was
being dragged down by a documentation signal that had nothing to do with
duplication, function length, or complexity, and the Findings page showed
the same gap twice. See DocumentationAgent._detect_missing_docstrings /
_detect_missing_api_docs for the (single) place this is now detected.

Phrasing previously made one Gemini request per finding. For a repo with a
lot of long functions / near-duplicates, that meant dozens of tiny
back-to-back requests per run — enough to trip the Gemini free-tier rate
limit (HTTP 429) well before a single one-off request against the same key
would. Findings are now collected first, then phrased in configurable
batches (`batch_size` — see Config.quality_agent_batch_size /
QUALITY_AGENT_BATCH_SIZE) in a single request per batch, with a per-item
fallback if a batch response can't be cleanly parsed back apart. Mock mode
is unaffected: it has no network cost, so it keeps phrasing one item at a
time for simplicity.

Detection (heuristics + vector-similarity retrieval, no network cost) and
drafting (the batched Gemini calls above) are also split into their own
`detect()` / `draft()` methods, rather than only living inside `run()`.
This lets the supervisor run `detect()` for this agent concurrently with
the other agents' own detection passes, then run the LLM-bound `draft()`
steps for Quality and Documentation sequentially afterwards — so their
Gemini requests don't land in the same burst and trip 429s. `run()` is
kept as a `detect()` + `draft()` wrapper for anyone calling it directly.

**Provider failover.** Batching and spacing address HTTP 429 (our quota).
They do nothing for a 503 UNAVAILABLE, which is the provider's capacity
and is unaffected by how slowly we ask — the fix there is a different
provider. This agent was constructed with a single raw `LLMClient` and had
no failover path at all, so a Gemini outage ended the run. It now accepts
an optional `ModelRouter` and drafts through it when one is supplied,
falling back to the bare client otherwise (keeping the existing
constructor signature working for direct callers and tests).

**Degradation instead of collapse.** The findings themselves come from
deterministic heuristics and vector similarity — no model involved. Only
the human-readable *description* needs one. Losing a whole audit because
the prose couldn't be generated is a bad trade, so a finding whose
description can't be drafted keeps its file, line, rule, severity and
evidence, and carries its heuristic summary as the description instead.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..llm.base import LLMClient
from ..llm.batching import build_batch_prompt, chunk_items, split_batch_response
from ..llm.router import ModelRouter
from ..memory.vector_store import VectorStore
from ..schemas import Category, Finding, Severity, make_finding
from ..tools.repo_reader import FileRecord
from ..tracing import Tracer

SYSTEM_PROMPT = (
    "You are a pragmatic code-quality reviewer. Given one code-smell "
    "heuristic result, write a 1-2 sentence, non-alarmist note explaining "
    "the smell and a concrete suggestion to improve it."
)

BATCH_INSTRUCTIONS = (
    "You are a pragmatic code-quality reviewer. Below are several independent "
    "code-smell heuristic results, each in its own numbered item. For each "
    "one, write a 1-2 sentence, non-alarmist note explaining the smell and a "
    "concrete suggestion to improve it."
)

DEFAULT_BATCH_SIZE = 8
DEFAULT_DUPLICATE_MIN_SCORE = 0.95
# Below this many non-import, non-blank lines, a "near-duplicate" chunk pair
# is almost always just two files sharing the same import block rather than
# genuinely duplicated logic — not worth reporting either way.
MIN_NON_IMPORT_LINES_FOR_DUPLICATE = 5


@dataclass
class _PendingFinding:
    """A finding whose Gemini-authored description hasn't been filled in
    yet — everything else `make_finding` needs, plus the heuristic summary
    text used to phrase it."""

    summary: str
    file: str
    line: int
    rule: str
    title: str
    severity: Severity
    evidence: str


def _non_import_line_count(text: str) -> int:
    """Number of non-blank lines in `text` that aren't plain import
    statements — used to filter out duplicate-code matches that are really
    just two files sharing the same import block."""
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            continue
        count += 1
    return count


class QualityAgent:
    def __init__(
        self,
        llm: LLMClient,
        vector_store: VectorStore,
        tracer: Tracer,
        long_function_threshold: int = 40,
        batch_size: int = DEFAULT_BATCH_SIZE,
        duplicate_min_score: float = DEFAULT_DUPLICATE_MIN_SCORE,
        router: ModelRouter | None = None,
        provider: str = "gemini",
    ) -> None:
        self.llm = llm
        self.vector_store = vector_store
        self.tracer = tracer
        self.long_function_threshold = long_function_threshold
        self.batch_size = max(1, batch_size)
        self.duplicate_min_score = duplicate_min_score
        # When supplied, drafting routes through here so a provider outage
        # fails over instead of ending the run. Optional so the existing
        # two-positional-arg construction used by tests keeps working.
        self.router = router
        self.provider = provider
        # Findings in the last `draft()` that kept their heuristic summary
        # because no provider could phrase them. Surfaced by the Supervisor.
        self.degraded_count = 0

    def detect(self, repo_id: str, files: list[FileRecord]) -> list[_PendingFinding]:
        """Heuristic pass only — no LLM calls. Returns findings pending a
        Gemini-authored description, so callers can run this concurrently
        with other agents' own detection passes and defer the LLM-bound
        `draft()` step until afterwards (see supervisor.py).

        Deliberately does NOT include missing-docstring detection —
        that's DocumentationAgent's responsibility (Category.DOCS), so it
        isn't reported twice under two different categories."""
        self.tracer.log("quality_agent", "scan.start", repo_id=repo_id, files=len(files))

        pending = (
            self._gather_long_functions(files)
            + self._gather_duplicate_code(repo_id)
        )

        self.tracer.log("quality_agent", "detect.done", pending=len(pending))
        return pending

    def draft(self, pending: list[_PendingFinding]) -> list[Finding]:
        """Phrases each pending finding via (batched) Gemini requests and
        assembles the final Finding objects."""
        descriptions = self._phrase_batch([p.summary for p in pending])

        findings: list[Finding] = [
            make_finding(
                file=p.file,
                line=p.line,
                category=Category.QUALITY,
                rule=p.rule,
                title=p.title,
                description=description,
                severity=p.severity,
                source_agent="quality",
                source_tool="heuristic",
                evidence=p.evidence,
            )
            for p, description in zip(pending, descriptions)
        ]

        self.tracer.log("quality_agent", "scan.done", findings=len(findings))
        return findings

    def run(self, repo_id: str, files: list[FileRecord]) -> list[Finding]:
        """Backward-compatible wrapper: detect() then draft()."""
        pending = self.detect(repo_id, files)
        return self.draft(pending)

    # ---- batched phrasing ------------------------------------------------

    def _complete(self, prompt: str, items: int = 1) -> str | None:
        """One completion, through the router when available so a provider
        outage fails over. Returns None when nothing could serve it.

        Every call is timed and traced. Diagnosing "why is drafting slow"
        was previously guesswork from stage-level durations alone — with
        per-request timing, prompt size and item count in the log, the
        answer is readable straight off the Audit page's streaming logs.
        """
        started = time.monotonic()
        text: str | None
        error: str | None

        if self.router is not None:
            text, error = self.router.complete_text(
                prompt, system=SYSTEM_PROMPT, profile="cheap", provider=self.provider
            )
        else:
            try:
                text, error = self.llm.complete(prompt, system=SYSTEM_PROMPT), None
            except Exception as exc:  # noqa: BLE001 - degrade rather than kill the run
                text, error = None, str(exc)

        elapsed = round(time.monotonic() - started, 2)
        self.tracer.log(
            "quality_agent", "draft.request",
            seconds=elapsed, items=items, prompt_chars=len(prompt), ok=error is None,
        )
        if error is not None:
            self.tracer.log(
                "quality_agent", "draft.provider_unavailable",
                error=error[:300], seconds=elapsed,
            )
            return None
        return text

    def _phrase_batch(self, summaries: list[str]) -> list[str]:
        """Phrase all `summaries` into descriptions, batching live requests
        `self.batch_size` at a time. Mock mode phrases one at a time (no
        network cost, and keeps deterministic per-item output)."""
        self.degraded_count = 0
        if not summaries:
            return []
        if getattr(self.llm, "mock", False):
            return [self.llm.complete(s, system=SYSTEM_PROMPT) for s in summaries]

        results: list[str] = []
        # Size-aware: see `chunk_items`. Capping on item count alone lets a
        # few long summaries build a prompt big enough to be slow and to
        # come back unsplittable, which then costs per-item retries.
        for batch in chunk_items(summaries, self.batch_size):
            results.extend(self._phrase_one_batch(batch))
        if self.degraded_count:
            self.tracer.log(
                "quality_agent", "draft.degraded",
                degraded=self.degraded_count, total=len(summaries),
            )
        return results

    def _phrase_one_batch(self, batch: list[str]) -> list[str]:
        if len(batch) == 1:
            text = self._complete(batch[0])
            if text is None:
                self.degraded_count += 1
                # The heuristic summary is already an accurate, if terser,
                # description of the finding — a strictly better fallback
                # than an empty string or a lost finding.
                return [batch[0]]
            return [text]

        response = self._complete(build_batch_prompt(batch, BATCH_INSTRUCTIONS), items=len(batch))

        if response is None:
            # Every provider refused. Retrying item-by-item would mean N
            # more full backoff cycles against an endpoint that just said
            # it can't serve us. Degrade the batch to its heuristic
            # summaries in one step instead.
            self.degraded_count += len(batch)
            return list(batch)

        parsed = split_batch_response(response, len(batch))
        if parsed is not None:
            return parsed

        # The call worked but the response didn't split cleanly. The
        # provider is demonstrably up, so per-item retries are worthwhile.
        self.tracer.log("quality_agent", "batch_parse_failed", batch_size=len(batch))
        out: list[str] = []
        for summary in batch:
            text = self._complete(summary)
            if text is None:
                self.degraded_count += 1
                out.append(summary)
            else:
                out.append(text)
        return out

    # ---- heuristics (gather findings without descriptions yet) -----------

    def _gather_long_functions(self, files: list[FileRecord]) -> list[_PendingFinding]:
        out: list[_PendingFinding] = []
        for rec in files:
            if rec.language != "python":
                continue
            self.tracer.log("quality_agent", "processing_file", file=rec.path)
            for chunk in rec.chunks:
                n_lines = chunk.text.count("\n") + 1
                if n_lines > self.long_function_threshold and chunk.text.lstrip().startswith(("def ", "async def ")):
                    summary = (
                        f"Function starting at {rec.path}:{chunk.start_line} is {n_lines} lines long "
                        f"(threshold {self.long_function_threshold}). Consider splitting it."
                    )
                    out.append(
                        _PendingFinding(
                            summary=summary,
                            file=rec.path,
                            line=chunk.start_line,
                            rule="long-function",
                            title=f"Long function ({n_lines} lines)",
                            severity=Severity.LOW,
                            evidence=chunk.text.splitlines()[0][:200],
                        )
                    )
        return out

    def _gather_duplicate_code(self, repo_id: str) -> list[_PendingFinding]:
        out: list[_PendingFinding] = []
        for a, b in self.vector_store.similar_chunks(repo_id, min_score=self.duplicate_min_score):
            # Filter out matches that are "duplicates" only because both
            # chunks share the same handful of import lines — these were
            # showing up as e.g. "tasks.py duplicate of users.py" purely
            # because both start with `from fastapi import APIRouter`,
            # which isn't a meaningful duplication signal.
            if _non_import_line_count(a["text"]) < MIN_NON_IMPORT_LINES_FOR_DUPLICATE:
                continue
            if _non_import_line_count(b["text"]) < MIN_NON_IMPORT_LINES_FOR_DUPLICATE:
                continue

            summary = (
                f"Code at {a['file']}:{a['start_line']} looks nearly identical to "
                f"{b['file']}:{b['start_line']}. Consider extracting a shared helper."
            )
            out.append(
                _PendingFinding(
                    summary=summary,
                    file=a["file"],
                    line=a["start_line"],
                    rule="duplicate-code",
                    title=f"Possible duplicate of {b['file']}:{b['start_line']}",
                    severity=Severity.LOW,
                    evidence=a["text"].splitlines()[0][:200],
                )
            )
        return out