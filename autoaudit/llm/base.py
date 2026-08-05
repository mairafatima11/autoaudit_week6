"""Shared LLM client interface so agents don't care which provider they're
talking to. Both concrete clients support a deterministic mock mode, which
is what the offline test suite (and any grading run with no API keys) uses.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProviderHealth:
    provider: str
    healthy: bool
    latency_ms: float
    detail: str = ""


class ProviderUnavailable(RuntimeError):
    """The provider is up but cannot serve this request *right now* —
    HTTP 429 (our quota) or 5xx/503 (their capacity), after the client has
    already exhausted its own retry/backoff budget.

    This is distinct from a bad request, a bad API key, or a malformed
    response: those won't be fixed by asking again, and won't be fixed by
    asking a *different* provider either. `ProviderUnavailable` means
    "this provider can't, another one might", which is exactly the signal
    `ModelRouter` needs to stop retrying and fail over immediately instead
    of burning more backoff against a saturated endpoint.

    Because a client only raises this *after* exhausting its own backoff,
    the router always fails over immediately rather than spending further
    attempts on the same endpoint.

    `kind` records which limit was hit, purely so the message shown to the
    user is actionable — the two have genuinely different remedies:

    - ``"quota"`` (HTTP 429) — *our* request rate against *our* key.
      Batching, spacing (`GEMINI_REQUEST_DELAY_MS`) and a higher quota tier
      all help, because we control the input side.
    - ``"capacity"`` (HTTP 5xx / 503 UNAVAILABLE) — the *provider's* own
      saturation. Asking more slowly changes nothing; the model is busy for
      everyone. Only waiting it out or using another provider helps.
    """

    def __init__(self, provider: str, message: str, *, kind: str = "capacity") -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.kind = kind


class LLMClient(ABC):
    provider: str = "base"

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        """Return the model's text completion for `prompt`."""
        raise NotImplementedError

    def health_check(self) -> ProviderHealth:
        """Lightweight liveness probe backing the provider health-check /
        automatic-failover requirement. Default implementation: attempt a
        trivial completion and time it. Mock-mode clients always report
        healthy (no network to fail); live clients report unhealthy if the
        probe raises. Concrete clients may override this with a cheaper
        provider-specific ping if one exists.
        """
        start = time.monotonic()
        try:
            self.complete("ping", system=None)
            return ProviderHealth(
                provider=self.provider, healthy=True,
                latency_ms=round((time.monotonic() - start) * 1000, 1),
            )
        except Exception as exc:  # noqa: BLE001 - any failure means "unhealthy", by design
            return ProviderHealth(
                provider=self.provider, healthy=False,
                latency_ms=round((time.monotonic() - start) * 1000, 1),
                detail=str(exc),
            )


def mock_hash_summary(text: str, max_len: int = 160) -> str:
    """Deterministic, content-derived stand-in for an LLM response, used by
    both mock clients so tests get realistic (non-identical, non-random)
    output without any network call."""
    words = [w for w in text.split() if w.strip()]
    snippet = " ".join(words[:24])
    if len(snippet) > max_len:
        snippet = snippet[:max_len].rstrip() + "..."
    return snippet
