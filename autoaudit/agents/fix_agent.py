"""Fix Agent (Week 7): for each finding, generates a proposed patch, PR
title/description, commit message, suggested tests, and impact/confidence
estimates.

Hard rule: this agent NEVER writes to the repository. It only returns
`FixProposal` objects for a human (or the Findings/Fixes UI) to review and
apply manually. See prompts.md, Week 7 entry.

**This runs while a user watches a spinner**, which makes its time budget a
correctness concern rather than a nicety. Two things previously made it
unbounded:

1. It resolved `router.clients[provider]` and called that client directly,
   bypassing `ModelRouter` — so no failover, no timeout and no circuit
   breaker applied, exactly the bug the other agents had.
2. Each finding costs up to four model calls (one draft plus
   `validate_with_repair`'s repair/fallback attempts), and findings were
   processed strictly one after another with no overall deadline. With a
   rate-limited provider at ~7s per call that is ~5 minutes for the default
   ten findings, with nothing shown until every one finished.

Now: every call goes through the router on the interactive budget, findings
are proposed concurrently, and the whole batch shares a wall-clock deadline.
Anything not drafted by the deadline still comes back — as a clearly
labelled deterministic proposal — so the user always gets a complete,
immediately useful response.
"""
from __future__ import annotations

import concurrent.futures
import re
import time

from ..llm.base import mock_hash_summary
from ..llm.router import ModelRouter
from ..llm.validation import ValidationFailure, validate_with_repair
from ..schemas import Finding, FixProposal, ImpactLevel, plain as _plain
from ..tools.source_utils import extract_source_snippet, extract_source_snippet_from_content
from ..tracing import Tracer

SYSTEM_PROMPT = (
    "You are a careful senior software engineer proposing a fix for a single "
    "code-review finding. You NEVER apply changes yourself — you only draft a "
    "proposal for a human to review. Respond with ONLY a JSON object matching "
    "this schema (no prose, no markdown fences):\n"
    "{"
    '"finding_fingerprint": str, "file": str, "patch": str (unified diff), '
    '"pr_title": str, "pr_description": str, "commit_message": str, '
    '"suggested_unit_test": str, "suggested_integration_test": str, '
    '"estimated_impact": "low"|"medium"|"high", "estimated_confidence": float 0-1'
    "}\n"
    "The patch must be a minimal, valid unified diff (---/+++/@@ headers) "
    "addressing only this finding. Keep other fields concise and concrete. "
    "The patch must contain only real code copied/adapted from the 'Surrounding "
    "code' you were given below — never placeholder text like '# rest of the "
    "logic' or '# N lines of setup' standing in for code you weren't shown, and "
    "never a reference to a helper module or import that isn't visible in the "
    "given context. If the given context isn't enough to write a complete, "
    "correct patch (e.g. a function's body is truncated), lower "
    "estimated_confidence and say so in pr_description rather than inventing "
    "the missing code."
)

# Findings whose title encodes the actual span of code the finding is about
# (e.g. "Long function (126 lines)" from QualityAgent) — for these, the fixed
# ~13-line window around `finding.line` used for every other finding only
# shows the function's signature and first few lines, not the body a
# refactor patch needs to reference. That starved context is what caused the
# Fix Agent to fabricate placeholder patches (e.g. "# 41 lines of setup
# logic" instead of real code, or a nonexistent "from utils.helpers import
# client") for long-function/duplicate-code findings — the model was asked
# to rewrite code it was never shown. Widening the snippet to the finding's
# actual line count (plus a small margin) gives it what it needs to write a
# real diff instead.
_SPAN_HINT_RE = re.compile(r"\((\d+)\s*lines?\)")
_DEFAULT_CONTEXT = 6
_MAX_CONTEXT = 200

# Wall-clock budget for one `propose_fixes` call, and how many findings are
# drafted concurrently. The endpoint is synchronous and a user is watching
# it, so it must return something useful in a predictable time rather than
# however long the slowest provider happens to take. Concurrency is kept
# modest on purpose: fanning out too wide against a rate-limited provider
# converts a latency problem into a 429 storm.
DEFAULT_BATCH_BUDGET_SECONDS = 90.0
DEFAULT_MAX_WORKERS = 4


def _context_lines_for(finding: Finding) -> int:
    match = _SPAN_HINT_RE.search(finding.title or "")
    if not match:
        return _DEFAULT_CONTEXT
    span = int(match.group(1))
    return min(_MAX_CONTEXT, max(_DEFAULT_CONTEXT, span + 4))


def _fallback_proposal(finding: Finding, error: str) -> FixProposal:
    """Deterministic, always-valid stand-in used when even the repair/
    fallback-model path can't produce schema-valid output — keeps a broken
    provider from ever blocking the pipeline, per the Week 7 'no invalid
    responses enter the pipeline' requirement."""
    return FixProposal(
        finding_fingerprint=finding.fingerprint,
        file=finding.file,
        patch=(
            f"--- a/{finding.file}\n+++ b/{finding.file}\n"
            f"@@ line {finding.line} @@\n"
            f"- (manual review required — automatic patch generation failed: {error})\n"
        ),
        pr_title=f"Fix: {finding.title}",
        pr_description=(
            f"Automatic patch generation failed ({error}). Manual review needed for "
            f"'{finding.title}' at {finding.file}:{finding.line}."
        ),
        commit_message=f"fix: address {finding.rule} at {finding.file}:{finding.line}",
        suggested_unit_test="Add a regression test covering this code path once fixed.",
        suggested_integration_test="Re-run the full audit and confirm this finding no longer appears.",
        estimated_impact=ImpactLevel.MEDIUM,
        estimated_confidence=0.1,
    )


def _mock_proposal(finding: Finding, snippet: str) -> FixProposal:
    """Deterministic proposal used when the primary LLM client is in mock
    mode (no API key / offline tests). Mirrors the shape a live model
    would return, without requiring the mock clients to fabricate JSON."""
    gist = mock_hash_summary(finding.description or finding.title)
    patch = (
        f"--- a/{finding.file}\n+++ b/{finding.file}\n"
        f"@@ -{max(finding.line, 1)},1 +{max(finding.line, 1)},1 @@\n"
        f"- {(snippet.splitlines()[len(snippet.splitlines()) // 2] if snippet else '# original line').strip()}\n"
        f"+ # TODO(review): address '{finding.rule}' — {gist}\n"
    )
    return FixProposal(
        finding_fingerprint=finding.fingerprint,
        file=finding.file,
        patch=patch,
        pr_title=f"Fix: {finding.title}",
        pr_description=(
            f"Addresses `{finding.rule}` flagged by the {finding.source_agent} agent at "
            f"{finding.file}:{finding.line}. {gist}"
        ),
        commit_message=f"fix({finding.category}): {finding.rule} in {finding.file}",
        suggested_unit_test=(
            f"Add a unit test for {finding.file} covering the {finding.rule} code path "
            f"to prevent regression."
        ),
        suggested_integration_test="Re-run `autoaudit run` on this repo and confirm the finding no longer appears.",
        estimated_impact=ImpactLevel.HIGH if finding.severity == "high" else (
            ImpactLevel.MEDIUM if finding.severity == "medium" else ImpactLevel.LOW
        ),
        estimated_confidence=0.55,
    )


class FixAgent:
    def __init__(
        self,
        router: ModelRouter,
        tracer: Tracer,
        root_path: str = "",
        files=None,
        primary_provider: str = "groq",
        fallback_provider: str = "gemini",
    ) -> None:
        self.router = router
        self.tracer = tracer
        self.root_path = root_path
        # `files` is the Repository Agent's FileRecord list, still held in
        # memory by the Supervisor for this run. It is the *primary* source
        # for patch context: for a cloned repo, `root_path` has already been
        # deleted by the time fixes are requested, so a disk read returns
        # nothing and the model is asked to patch code it was never shown.
        # Indexed by path here so per-finding lookup stays O(1).
        self._content_by_path: dict[str, str] = {
            f.path: f.content for f in (files or []) if getattr(f, "content", None)
        }
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

    def _snippet_for(self, finding: Finding) -> str:
        """Patch context for `finding`, preferring in-memory file content
        over a disk read (see `__init__`). Returns "" if neither is
        available, in which case the prompt's grounding rules tell the model
        to lower its confidence rather than invent the missing code."""
        context = _context_lines_for(finding)

        content = self._content_by_path.get(finding.file)
        if content:
            snippet = extract_source_snippet_from_content(content, finding.line, context=context)
            if snippet:
                return snippet

        if self.root_path:
            return extract_source_snippet(
                self.root_path, finding.file, finding.line, context=context
            ) or ""
        return ""

    def propose_fix(self, finding: Finding, deadline: float | None = None) -> FixProposal:
        self.tracer.log("fix_agent", "propose.start", fingerprint=finding.fingerprint, file=finding.file)

        snippet = self._snippet_for(finding)

        prompt = (
            f"Finding: {finding.title}\n"
            f"File: {finding.file}:{finding.line}\n"
            f"Category: {finding.category}\n"
            f"Severity: {finding.severity}\n"
            f"Description: {finding.description}\n"
            f"Evidence:\n{(finding.evidence or '')[:400]}\n\n"
            f"Surrounding code:\n{snippet[:6000]}\n\n"
            f'Set "finding_fingerprint" to exactly "{finding.fingerprint}" and "file" to exactly "{finding.file}".'
        )

        primary = self.router.clients.get(self.primary_provider) or next(iter(self.router.clients.values()))
        fallback = self.router.clients.get(self.fallback_provider)

        if getattr(primary, "mock", False):
            proposal = _mock_proposal(finding, snippet)
            self.tracer.log("fix_agent", "propose.done", fingerprint=finding.fingerprint, repaired=False, model_used="mock")
            return proposal

        if deadline is not None and time.monotonic() >= deadline:
            return _fallback_proposal(finding, "time budget for this batch was exhausted")

        # Routed, not called directly: this is what gives the drafting call
        # provider failover, a bounded timeout and the circuit breaker.
        raw, error = self.router.complete_text(
            prompt, system=SYSTEM_PROMPT, profile="precision",
            provider=self.primary_provider, interactive=True, deadline=deadline,
        )
        if error is not None:
            self.tracer.log("fix_agent", "propose.provider_unavailable", fingerprint=finding.fingerprint, error=error[:300])
            return _fallback_proposal(finding, error)

        try:
            result = validate_with_repair(
                FixProposal,
                raw,
                primary_client=primary,
                fallback_client=fallback,
                original_prompt=prompt,
                system=SYSTEM_PROMPT,
            )
            proposal = result.value
            # Guard against the model drifting from the requested identifiers.
            proposal.finding_fingerprint = finding.fingerprint
            proposal.file = finding.file
            self.tracer.log(
                "fix_agent", "propose.done",
                fingerprint=finding.fingerprint,
                repaired=result.repaired,
                model_used=result.model_used,
            )
            return proposal
        except ValidationFailure as exc:
            self.tracer.log("fix_agent", "propose.validation_failed", fingerprint=finding.fingerprint, error=str(exc))
            return _fallback_proposal(finding, str(exc))

    def propose_fixes(
        self,
        findings: list[Finding],
        max_findings: int | None = None,
        budget_seconds: float | None = DEFAULT_BATCH_BUDGET_SECONDS,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> list[FixProposal]:
        """Propose fixes for up to `max_findings` findings, within
        `budget_seconds` overall.

        Findings tagged `fixed` are history entries the audit-history diff
        reconstructs for issues that are *no longer in the code* — asking
        the model to patch them wastes the budget on code that isn't there
        and produces nonsense diffs. They're skipped before `max_findings`
        is applied, so the cap still yields that many real proposals.

        Proposals run concurrently and share one wall-clock deadline. The
        returned list always has one entry per target, in the original
        order: anything that couldn't be drafted in time comes back as a
        clearly-labelled deterministic proposal rather than being omitted,
        so the caller never has to distinguish "no fix" from "not finished".
        """
        actionable = [f for f in findings if _plain(f.status) != "fixed"]
        targets = actionable if max_findings is None else actionable[:max_findings]
        if not targets:
            return []

        deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
        workers = max(1, min(max_workers, len(targets)))

        self.tracer.log(
            "fix_agent", "batch.start",
            findings=len(targets), workers=workers, budget_seconds=budget_seconds,
        )

        proposals: list[FixProposal | None] = [None] * len(targets)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._propose_one_safely, finding, deadline): index
                for index, finding in enumerate(targets)
            }
            for future in concurrent.futures.as_completed(futures):
                proposals[futures[future]] = future.result()

        results = [
            p if p is not None else _fallback_proposal(targets[i], "no proposal was produced")
            for i, p in enumerate(proposals)
        ]
        degraded = sum(1 for p in results if "manual review required" in p.patch)
        self.tracer.log("fix_agent", "batch.done", proposals=len(results), degraded=degraded)
        return results

    def _propose_one_safely(self, finding: Finding, deadline: float | None) -> FixProposal:
        """Never let one finding's failure take down the batch — a raised
        exception here would propagate out of the pool and lose every other
        proposal, including ones that already succeeded."""
        try:
            return self.propose_fix(finding, deadline=deadline)
        except Exception as exc:  # noqa: BLE001 - one bad finding must not sink the batch
            self.tracer.log("fix_agent", "propose.failed", fingerprint=finding.fingerprint, error=str(exc)[:300])
            return _fallback_proposal(finding, str(exc))