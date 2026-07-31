"""Shared LLM client interface so agents don't care which provider they're
talking to. Both concrete clients support a deterministic mock mode, which
is what the offline test suite (and any grading run with no API keys) uses.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMClient(ABC):
    provider: str = "base"

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        """Return the model's text completion for `prompt`."""
        raise NotImplementedError


def mock_hash_summary(text: str, max_len: int = 160) -> str:
    """Deterministic, content-derived stand-in for an LLM response, used by
    both mock clients so tests get realistic (non-identical, non-random)
    output without any network call."""
    words = [w for w in text.split() if w.strip()]
    snippet = " ".join(words[:24])
    if len(snippet) > max_len:
        snippet = snippet[:max_len].rstrip() + "..."
    return snippet
