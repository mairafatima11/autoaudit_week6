"""Model Router: Week 7 multi-model routing.

Wraps the existing GroqClient/GeminiClient (both already support a
deterministic mock mode — see llm/base.py) with:

- routing strategy   -> pick a provider based on task type / cost profile
- fallback strategy  -> if the primary provider errors or times out, retry
                         on the secondary provider
- retry strategy     -> bounded retries with exponential backoff per call
- timeout strategy    -> wall-clock budget per attempt via a worker thread
                         (works for both mock and live calls, no provider
                         SDK changes required)
- cost optimization  -> cheap/fast tasks default to the configured
                         "cheap" provider unless explicitly overridden
- comparison         -> run N providers on the same prompt and diff them

This module deliberately does not import agents; it's a low-level utility
consumed by Supervisor / Fix Agent / Documentation Agent / the API layer.
"""
from __future__ import annotations

import concurrent.futures
import threading
import time
from dataclasses import dataclass, field

from .base import LLMClient, ProviderUnavailable
from ..schemas import ModelComparison, ModelRunResult
from ..tools.embeddings import cosine_similarity, embed_text

TaskProfile = str  # "precision" | "cheap" | "bulk"


@dataclass
class RouterConfig:
    max_retries: int = 2
    retry_backoff_seconds: float = 0.2
    # Wall-clock budget for a single provider call in *background* work
    # (batched drafting during an audit). Generous on purpose: the clients
    # use a 60s per-request HTTP timeout and retry several times with
    # exponential backoff, so their legitimate worst case is minutes, and a
    # short budget here would kill calls that are still making progress.
    timeout_seconds: float = 240.0
    # Budget for work a human is actively waiting on (the AI Comparison
    # page, on-demand fix proposals). These must fail fast and say so:
    # nobody watches a spinner for four minutes to find out a provider was
    # degraded. Applying the background budget to interactive endpoints —
    # 240s x 3 retries x 2 providers x an extra judge call — put the
    # comparison endpoint's worst case at ~48 minutes, which is
    # indistinguishable from a hang.
    interactive_timeout_seconds: float = 45.0
    # How long a provider that reported itself unavailable is skipped for.
    # Without this, a full outage costs every *subsequent* call another
    # complete retry/backoff cycle per provider: on a 100-file repo that's
    # dozens of batches x every provider x seconds of backoff, all of it
    # already known to be doomed. Short enough that a brief spike doesn't
    # sideline a provider for the rest of the run.
    unavailable_cooldown_seconds: float = 45.0
    # Which provider is preferred for each task profile. Falls back to the
    # other registered provider if the preferred one errors/times out.
    profile_preference: dict[TaskProfile, str] = field(
        default_factory=lambda: {
            "precision": "groq",        # security-sensitive reasoning (Llama 3.3 70B)
            "cheap": "gemini",          # high-volume, low-stakes reasoning
            "bulk": "gemini",
        }
    )


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider


def _estimate_tokens(text: str) -> int:
    # Cheap, deterministic heuristic (~4 chars/token), good enough for a
    # comparison UI without depending on a provider-specific tokenizer.
    return max(1, len(text) // 4)


def _estimate_confidence(response: str) -> float:
    """Deterministic confidence heuristic used when a provider doesn't
    return one natively: longer, non-empty, non-error responses score
    higher, capped in [0.3, 0.95] so it never claims certainty."""
    if not response.strip():
        return 0.0
    length_score = min(len(response) / 400.0, 1.0)
    return round(0.3 + 0.65 * length_score, 2)


class ModelRouter:
    def __init__(
        self,
        clients: dict[str, LLMClient],
        config: RouterConfig | None = None,
    ) -> None:
        """`clients` maps provider name ("groq", "gemini") -> LLMClient."""
        self.clients = clients
        self.config = config or RouterConfig()
        # Circuit breaker: provider -> monotonic time until which it is
        # skipped. Guarded by a lock because agents call one shared router
        # from several threads.
        self._unavailable_until: dict[str, float] = {}
        self._breaker_lock = threading.Lock()

    def _is_cooling_down(self, provider: str) -> bool:
        with self._breaker_lock:
            until = self._unavailable_until.get(provider)
            if until is None:
                return False
            if time.monotonic() >= until:
                del self._unavailable_until[provider]
                return False
            return True

    def _trip_breaker(self, provider: str) -> None:
        with self._breaker_lock:
            self._unavailable_until[provider] = (
                time.monotonic() + self.config.unavailable_cooldown_seconds
            )

    def _reset_breaker(self, provider: str) -> None:
        with self._breaker_lock:
            self._unavailable_until.pop(provider, None)

    # ---- single-call routing with fallback/retry/timeout -----------------

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        profile: TaskProfile = "precision",
        provider: str | None = None,
        interactive: bool = False,
        deadline: float | None = None,
    ) -> ModelRunResult:
        """Route a single completion. Tries the preferred/explicit provider
        first; on error or timeout, falls back to any other registered
        provider before giving up.

        `interactive=True` applies the short latency budget meant for
        requests a human is waiting on. `deadline` is an absolute
        `time.monotonic()` value capping the whole call, so a caller
        looping over many items can bound its *total* time rather than
        only each individual request.
        """
        preferred = provider or self.config.profile_preference.get(profile, next(iter(self.clients)))
        order = [preferred] + [p for p in self.clients if p != preferred]

        if interactive:
            budget = self.config.interactive_timeout_seconds
            # For interactive work the budget bounds the *whole* routed call,
            # not each attempt. Applying it per attempt still let 3 retries x
            # 2 providers stretch a stalled provider to several minutes — and
            # retrying something that just failed to answer within the budget
            # mostly reproduces the same wait. A deadline makes the number the
            # user actually experiences match the number configured.
            if deadline is None:
                deadline = time.monotonic() + budget
        else:
            budget = self.config.timeout_seconds

        last_error: str | None = None
        attempted = False
        for provider_name in order:
            client = self.clients.get(provider_name)
            if client is None:
                continue
            # Skip a provider that very recently declared itself
            # unavailable — re-asking costs a full backoff cycle to learn
            # what we already know.
            if self._is_cooling_down(provider_name):
                last_error = f"[{provider_name}] skipped: unavailable, cooling down"
                continue

            remaining = budget
            if deadline is not None:
                remaining = min(remaining, deadline - time.monotonic())
                if remaining <= 0:
                    last_error = last_error or "deadline exceeded before a provider could be tried"
                    break

            attempted = True
            result = self._call_with_retry(client, prompt, system, remaining, deadline)
            if result.error is None:
                self._reset_breaker(provider_name)
                return result
            last_error = result.error

        if not attempted and self.clients:
            # Every provider is cooling down. Return immediately rather than
            # blocking; callers degrade gracefully on `error`.
            return ModelRunResult(
                provider=preferred, model="unknown", response="",
                latency_ms=0.0, token_estimate=0, confidence=0.0,
                error=last_error or "all providers unavailable",
            )

        return ModelRunResult(
            provider=preferred,
            model="unknown",
            response="",
            latency_ms=0.0,
            token_estimate=0,
            confidence=0.0,
            error=last_error or "no providers configured",
        )

    def _call_with_retry(
        self,
        client: LLMClient,
        prompt: str,
        system: str | None,
        timeout_seconds: float | None = None,
        deadline: float | None = None,
    ) -> ModelRunResult:
        attempts = self.config.max_retries + 1
        budget = self.config.timeout_seconds if timeout_seconds is None else timeout_seconds
        last_err = None
        for attempt in range(attempts):
            start = time.monotonic()
            per_attempt = budget
            if deadline is not None:
                per_attempt = min(per_attempt, deadline - time.monotonic())
                if per_attempt <= 0:
                    last_err = last_err or "deadline exceeded"
                    break
            try:
                response = self._call_with_timeout(client, prompt, system, per_attempt)
                latency_ms = (time.monotonic() - start) * 1000
                return ModelRunResult(
                    provider=client.provider,
                    model=getattr(client, "model", "unknown"),
                    response=response,
                    latency_ms=round(latency_ms, 2),
                    token_estimate=_estimate_tokens(prompt) + _estimate_tokens(response),
                    confidence=_estimate_confidence(response),
                    error=None,
                )
            except ProviderUnavailable as exc:
                # A client only raises this after exhausting its *own*
                # retry/backoff budget, so the router spending further
                # attempts on the same endpoint just delays the failover
                # that will actually serve the request. This matters most
                # for a 503 ("model experiencing high demand"): that's the
                # provider's capacity, identical however patiently we ask,
                # and no amount of batching or spacing touches it. Break out
                # and let `complete()` move to the next provider now.
                last_err = str(exc)
                self._trip_breaker(client.provider)
                break
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any provider failure triggers fallback
                last_err = str(exc)
                if attempt < attempts - 1:
                    time.sleep(self.config.retry_backoff_seconds * (2 ** attempt))
        return ModelRunResult(
            provider=client.provider,
            model=getattr(client, "model", "unknown"),
            response="",
            latency_ms=0.0,
            token_estimate=0,
            confidence=0.0,
            error=last_err,
        )

    def complete_text(
        self,
        prompt: str,
        system: str | None = None,
        profile: TaskProfile = "cheap",
        provider: str | None = None,
        interactive: bool = False,
        deadline: float | None = None,
    ) -> tuple[str | None, str | None]:
        """Convenience wrapper over `complete()` returning
        `(text, error)` — exactly one of which is set.

        Agents that just want a string previously reached past the router
        into `router.clients[...]` and called the raw client directly, which
        silently bypassed every bit of fallback/retry/timeout logic this
        class exists to provide. This gives them the plain-text ergonomics
        they wanted without giving up provider failover.
        """
        result = self.complete(
            prompt, system=system, profile=profile, provider=provider,
            interactive=interactive, deadline=deadline,
        )
        if result.error is not None:
            return None, result.error
        return result.response, None

    def _call_with_timeout(
        self, client: LLMClient, prompt: str, system: str | None, timeout_seconds: float
    ) -> str:
        # NOT a `with` block. `ThreadPoolExecutor.__exit__` calls
        # `shutdown(wait=True)`, which blocks until the worker finishes — so
        # the previous context-managed version didn't bound anything: a call
        # that overran the timeout still ran to completion, and the caller
        # waited the full duration only to then be handed a TimeoutError.
        # With three retry attempts that turned a 3s hang into 9s of waiting
        # rather than the intended 1s. Shutting down without waiting lets the
        # abandoned request finish in the background while we move on.
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(client.complete, prompt, system)
            try:
                return future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError as exc:
                future.cancel()
                raise ProviderError(client.provider, f"timed out after {timeout_seconds}s") from exc
        finally:
            pool.shutdown(wait=False)

    # ---- side-by-side comparison ------------------------------------------

    def compare(
        self,
        prompt: str,
        system: str | None = None,
        providers: list[str] | None = None,
    ) -> ModelComparison:
        """Run the same prompt on every requested provider (default: all
        registered) in parallel and return a structured comparison."""
        targets = providers or list(self.clients.keys())
        results: list[ModelRunResult] = []
        # A human is watching this page, so every leg runs on the short
        # interactive budget rather than the background-audit one — and the
        # deadline bounds all retries together, not each attempt.
        budget = self.config.interactive_timeout_seconds
        deadline = time.monotonic() + budget

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(targets))) as pool:
            futures = {
                pool.submit(
                    self._call_with_retry, self.clients[p], prompt, system, budget, deadline
                ): p
                for p in targets
                if p in self.clients
            }
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        # Deterministic ordering for display/testing.
        results.sort(key=lambda r: r.provider)

        successful = [r for r in results if r.error is None]
        agreement, differences, merged = self._merge(prompt, successful)

        return ModelComparison(
            prompt=prompt,
            results=results,
            agreement=agreement,
            differences=differences,
            merged_answer=merged,
            reasoning_summary=self._reasoning_summary(results, agreement),
        )

    @staticmethod
    def _reasoning_summary(results: list[ModelRunResult], agreement: bool) -> str:
        """Short, explicit explanation of *why* the merged answer was
        chosen — separate from `differences` (which describes what
        diverged) so the UI can show 'how we decided' as its own field."""
        successful = [r for r in results if r.error is None]
        if not successful:
            return "No provider returned a usable response, so no merge could be performed."
        if len(successful) == 1:
            return f"Only {successful[0].provider} returned a result; it was used as-is."
        best = max(successful, key=lambda r: r.confidence)
        if agreement:
            return (
                f"Providers substantially agreed, so {best.provider}'s response "
                f"(highest confidence, {best.confidence:.0%}) was used as the merged answer."
            )
        return (
            f"Providers diverged; {best.provider}'s response was selected as the merged answer "
            f"based on highest confidence ({best.confidence:.0%}) among {len(successful)} responses."
        )

    JUDGE_SYSTEM_PROMPT = (
        "You compare two AI-generated answers to the same question and judge "
        "whether they substantively agree — same overall conclusion or "
        "recommendation, even if worded very differently — or disagree — "
        "different or conflicting conclusions, even if they share a lot of the "
        "same vocabulary. Respond with exactly one line, either "
        "'AGREE: <one short sentence why>' or 'DISAGREE: <one short sentence why>'. "
        "Nothing else."
    )

    def _judge_agreement(self, prompt: str, texts: list[str]) -> tuple[bool, str] | None:
        """Ask an LLM whether the two responses actually agree. Returns
        None (caller falls back to the heuristic) if the call errors or
        the response doesn't parse as AGREE/DISAGREE — including in mock
        mode, where the deterministic mock client just echoes the prompt
        back rather than reasoning about it."""
        judge_prompt = (
            f"Question asked: {prompt}\n\n"
            f"Answer A:\n{texts[0][:2000]}\n\n"
            f"Answer B:\n{texts[-1][:2000]}\n\n"
            "Do Answer A and Answer B substantively agree?"
        )
        try:
            # Interactive: this is an *extra* leg on top of the two provider
            # calls the user asked for, so it must never be the reason the
            # page sits spinning. If it can't answer quickly the caller
            # silently falls back to the similarity heuristic below.
            result = self.complete(
                judge_prompt, system=self.JUDGE_SYSTEM_PROMPT, profile="cheap", interactive=True
            )
        except Exception:
            return None
        if result.error:
            return None
        text = result.response.strip()
        upper = text.upper()
        if upper.startswith("AGREE"):
            reason = text.split(":", 1)[1].strip() if ":" in text else "The responses reached the same overall conclusion."
            return True, reason
        if upper.startswith("DISAGREE"):
            reason = text.split(":", 1)[1].strip() if ":" in text else "The responses reached different conclusions."
            return False, reason
        return None

    def _merge(self, prompt: str, results: list[ModelRunResult]) -> tuple[bool, str, str]:
        if not results:
            return False, "No successful responses to compare.", ""
        if len(results) == 1:
            return True, "Only one provider returned a result.", results[0].response

        texts = [r.response.strip() for r in results]
        best = max(results, key=lambda r: r.confidence)

        # Primary path: ask an LLM to actually judge agreement. A raw
        # word-overlap ratio (the previous approach) or even a weighted
        # bag-of-words cosine similarity (tried as a replacement — see
        # the fallback below) both measure topical similarity, not
        # agreement: two answers that reach opposite conclusions about the
        # same topic still share most of their vocabulary and score *high*
        # on those metrics, which is exactly backwards. Only a judge that
        # reads both answers can tell "agree" from "disagree".
        judged = self._judge_agreement(prompt, texts)
        if judged is not None:
            agreement, reason = judged
            if agreement:
                differences = f"An LLM judge found the responses substantively agree: {reason}"
            else:
                differences = (
                    f"An LLM judge found the responses substantively disagree: {reason} "
                    f"Highest-confidence provider ({best.provider}) was used for the merged answer."
                )
            return agreement, differences, best.response

        # Fallback only: the judge call failed (offline/mock mode, or a
        # provider outage) so there's no real judgment available. This
        # topical-similarity heuristic is explicitly *not* a substitute for
        # one — it's labeled as an estimate in the UI copy on purpose, since
        # it can't reliably separate "same topic, same conclusion" from
        # "same topic, opposite conclusion".
        similarity = cosine_similarity(embed_text(texts[0]), embed_text(texts[-1]))
        agreement = similarity >= 0.3
        if agreement:
            differences = (
                f"Responses appear topically similar (~{similarity:.0%}, heuristic estimate — "
                "no LLM judge available); treated as in agreement."
            )
        else:
            differences = (
                f"Responses appear to diverge (~{similarity:.0%} similarity, heuristic estimate — "
                f"no LLM judge available). Highest-confidence provider ({best.provider}) was used "
                "for the merged answer."
            )
        return agreement, differences, best.response
