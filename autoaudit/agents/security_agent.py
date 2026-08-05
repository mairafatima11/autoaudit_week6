"""Security Agent: runs static analysis (Semgrep, or the offline fallback
scanner) and uses Groq (Llama 3.3 70B) to turn each raw finding into a
human-readable, context-aware description, grounded in the retrieved code
chunk from the Repository Knowledge Base.

**The finding is not the description.** Detection here is entirely
deterministic — Semgrep (or the offline fallback scanner) decides what is
and isn't a vulnerability; the model only phrases the explanation. Losing a
model call therefore must not lose a *security finding*. This agent used to
call a bare `LLMClient` with no failover and no error handling, so a
provider outage mid-scan raised straight out of `Supervisor.run()` and
discarded every already-detected vulnerability along with the rest of the
run. It now drafts through `ModelRouter` when one is supplied (failing over
to the secondary provider) and falls back to the raw static-analysis
message when no provider can be reached — a terser description, but the
finding, its severity and its evidence are unchanged.

**Batched drafting.** This was the last agent still issuing one live model
request per finding, sequentially. Quality and Documentation were converted
to batched drafting to stop them tripping rate limits; Security was missed,
and it is the worst place to leave unbatched because Semgrep's `--config=auto`
can return hundreds of findings on a mid-sized repository. One request each,
end to end, meant a Flask scan spent minutes here — and because Security ran
inside the Supervisor's parallel phase, *nothing else could finish until it
did*. Explanations are now written in configurable batches
(`SECURITY_AGENT_BATCH_SIZE`), with a per-item retry only when a batch
response can't be split cleanly.

**detect() / draft() split.** Matching the other two agents. `detect()` is
pure static analysis plus vector retrieval — deterministic, no network — so
the Supervisor can run it concurrently with the other agents' detection
passes, then run the model-bound `draft()` afterwards. Previously Security's
LLM work sat inside the parallel phase and blocked it; the live pipeline view
showed Security spinning for minutes with everything behind it stalled.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..llm.base import LLMClient
from ..llm.batching import build_batch_prompt, chunk_items, split_batch_response
from ..llm.router import ModelRouter
from ..memory.vector_store import VectorStore
from ..schemas import Category, Finding, Severity, make_finding
from ..tools import static_analysis
from ..tools.repo_reader import FileRecord
from ..tools.source_utils import extract_source_snippet
from ..tracing import Tracer


SYSTEM_PROMPT = (
    "You are a precise, conservative application-security reviewer. "
    "Given one static-analysis finding and its surrounding code, explain in "
    "1-2 sentences why it's risky and what a safe fix looks like. Do not "
    "invent details not present in the evidence."
)

BATCH_INSTRUCTIONS = (
    "You are a precise, conservative application-security reviewer. Below are "
    "several independent static-analysis findings, each in its own numbered "
    "item. For each one, explain in 1-2 sentences why it's risky and what a "
    "safe fix looks like. Do not invent details not present in the evidence."
)

DEFAULT_BATCH_SIZE = 8


@dataclass
class _PendingFinding:
    """A detected vulnerability whose explanation hasn't been written yet.
    Everything needed to build the final `Finding` is already here — the
    model only supplies prose."""

    prompt: str
    file: str
    line: int
    rule: str
    message: str
    severity: str
    evidence: str
    source_tool: str


class SecurityAgent:
    def __init__(
        self,
        llm: LLMClient,
        vector_store: VectorStore,
        tracer: Tracer,
        router: ModelRouter | None = None,
        provider: str = "groq",
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.llm = llm
        self.vector_store = vector_store
        self.tracer = tracer
        # Optional so the existing three-positional-arg construction used by
        # tests keeps working; supplied by the Supervisor in real runs.
        self.router = router
        self.provider = provider
        self.batch_size = max(1, batch_size)
        self.degraded_count = 0

    # ---- detection (deterministic, no network) --------------------------

    def detect(
        self,
        repo_id: str,
        root_path: str,
        files: list[FileRecord],
    ) -> list[_PendingFinding]:
        """Static analysis + knowledge-base retrieval only. No model calls,
        so this is safe to run concurrently with the other agents' detection
        passes."""
        self.tracer.log("security_agent", "scan.start", repo_id=repo_id, files=len(files))

        file_pairs = [(f.path, f.content) for f in files]
        # Timed explicitly: `semgrep --config=auto` fetches its rule packs
        # over the network and can run for minutes on a large repository.
        # Without this, that time was invisible and looked like the agent
        # hanging.
        scan_started = time.monotonic()
        raw_findings = static_analysis.scan(root_path, file_pairs)
        scan_seconds = round(time.monotonic() - scan_started, 2)

        self.tracer.log(
            "security_agent",
            "static_analysis.done",
            count=len(raw_findings),
            tool=(raw_findings[0].source_tool if raw_findings else "none"),
            seconds=scan_seconds,
        )

        pending: list[_PendingFinding] = []
        for rf in raw_findings:
            self.tracer.log("security_agent", "processing_file", file=rf.file, rule=rf.rule)

            context = self.vector_store.query(repo_id, f"{rf.file} {rf.rule} {rf.message}", top_k=3)
            context_text = "\n\n".join(c["text"] for c in context[:3])

            snippet = extract_source_snippet(root_path, rf.file, rf.line)
            evidence = snippet or (rf.evidence or "").strip()
            if not evidence:
                evidence = "No source snippet available."

            pending.append(
                _PendingFinding(
                    prompt=(
                        f"Rule: {rf.rule}\n"
                        f"File: {rf.file}:{rf.line}\n"
                        f"Static-analysis message: {rf.message}\n\n"
                        f"Evidence:\n{evidence[:400]}\n\n"
                        f"Repository context:\n{context_text[:800]}"
                    ),
                    file=rf.file,
                    line=rf.line,
                    rule=rf.rule,
                    message=rf.message,
                    severity=rf.severity,
                    evidence=evidence,
                    source_tool=rf.source_tool,
                )
            )

        self.tracer.log("security_agent", "detect.done", pending=len(pending))
        return pending

    # ---- drafting (batched model calls) ---------------------------------

    def _complete(self, prompt: str, items: int = 1) -> str | None:
        """One routed completion. None when no provider could serve it, so
        the caller degrades rather than losing the security finding.

        Timed and traced per request — see QualityAgent._complete."""
        started = time.monotonic()
        text: str | None
        error: str | None

        if self.router is not None:
            text, error = self.router.complete_text(
                prompt, system=SYSTEM_PROMPT, profile="precision", provider=self.provider
            )
        else:
            try:
                text, error = self.llm.complete(prompt, system=SYSTEM_PROMPT), None
            except Exception as exc:  # noqa: BLE001 - never lose a finding over prose
                text, error = None, str(exc)

        elapsed = round(time.monotonic() - started, 2)
        self.tracer.log(
            "security_agent", "explain.request",
            seconds=elapsed, items=items, prompt_chars=len(prompt), ok=error is None,
        )
        if error is not None:
            self.tracer.log(
                "security_agent", "explain.provider_unavailable",
                error=error[:300], seconds=elapsed,
            )
            return None
        return text

    def _explain_batch(self, pending: list[_PendingFinding]) -> list[str]:
        if not pending:
            return []
        if getattr(self.llm, "mock", False):
            return [self.llm.complete(p.prompt, system=SYSTEM_PROMPT) for p in pending]

        # Size-aware batching: security prompts carry an evidence snippet
        # plus retrieved repository context, so item count alone is a poor
        # proxy for prompt size. See `chunk_items`.
        out: list[str] = []
        for batch in chunk_items(pending, self.batch_size, size_of=lambda p: len(p.prompt)):
            out.extend(self._explain_one_batch(batch))
        return out

    def _explain_one_batch(self, batch: list[_PendingFinding]) -> list[str]:
        def _degrade(item: _PendingFinding) -> str:
            # The static-analysis message already describes the
            # vulnerability accurately, just tersely.
            return (
                f"{item.message} [description not drafted — no model provider was "
                f"available; detection is unaffected.]"
            )

        if len(batch) == 1:
            text = self._complete(batch[0].prompt)
            if text is None:
                self.degraded_count += 1
                return [_degrade(batch[0])]
            return [text]

        response = self._complete(
            build_batch_prompt([p.prompt for p in batch], BATCH_INSTRUCTIONS), items=len(batch)
        )

        if response is None:
            # Every provider refused. Per-item retries would mean N more full
            # backoff cycles against an endpoint that just declined us.
            self.degraded_count += len(batch)
            return [_degrade(p) for p in batch]

        parsed = split_batch_response(response, len(batch))
        if parsed is not None:
            return parsed

        # Call succeeded but the response didn't split cleanly — the provider
        # is demonstrably up, so per-item retries are worthwhile here.
        self.tracer.log("security_agent", "batch_parse_failed", batch_size=len(batch))
        out: list[str] = []
        for item in batch:
            text = self._complete(item.prompt)
            if text is None:
                self.degraded_count += 1
                out.append(_degrade(item))
            else:
                out.append(text)
        return out

    def draft(self, pending: list[_PendingFinding]) -> list[Finding]:
        """Write each pending finding's explanation via batched model
        requests and assemble the final `Finding` objects."""
        self.degraded_count = 0
        explanations = self._explain_batch(pending)

        findings = [
            make_finding(
                file=p.file,
                line=p.line,
                category=Category.SECURITY,
                rule=p.rule,
                title=p.message,
                description=explanation,
                severity=Severity(p.severity),
                source_agent="security",
                source_tool=p.source_tool,
                evidence=p.evidence,
            )
            for p, explanation in zip(pending, explanations)
        ]

        if self.degraded_count:
            self.tracer.log(
                "security_agent", "explain.degraded",
                degraded=self.degraded_count, total=len(pending),
            )

        self.tracer.log(
            "security_agent", "scan.done",
            findings=len(findings), degraded=self.degraded_count,
        )
        return findings

    def run(
        self,
        repo_id: str,
        root_path: str,
        files: list[FileRecord],
    ) -> list[Finding]:
        """Backward-compatible wrapper: detect() then draft()."""
        return self.draft(self.detect(repo_id, root_path, files))
