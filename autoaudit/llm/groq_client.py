"""Groq client — powers the Security Agent (careful, high-precision
interpretation of static-analysis evidence). Uses Groq's OpenAI-compatible
chat-completions endpoint with Llama 3.3 70B, chosen for strong reasoning
quality at low latency/cost with no paid Anthropic dependency.

Groq is also the **failover target** when Gemini is unavailable (see
`llm/registry.py`, `llm/router.py`). That makes its own resilience matter:
it previously issued a single un-retried request and let `raise_for_status`
surface a raw `requests.HTTPError`, so a momentary blip on the failover
provider defeated the whole point of having one. It now mirrors the Gemini
client's contract — retry with backoff on 429/5xx, and raise
`ProviderUnavailable` (rather than an opaque error) when it genuinely can't
serve the request, so the router can classify the failure correctly.
"""
from __future__ import annotations

import time

import requests

from .base import LLMClient, ProviderUnavailable, mock_hash_summary

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

DEFAULT_MAX_RETRIES = 3
MAX_BACKOFF_SECONDS = 30.0


class GroqClient(LLMClient):
    provider = "groq"

    def __init__(
        self,
        api_key: str = "",
        model: str = "llama-3.3-70b-versatile",
        mock: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.mock = mock or not api_key
        self.max_retries = max_retries

    def complete(self, prompt: str, system: str | None = None) -> str:
        if self.mock:
            return self._mock_complete(prompt, system)
        return self._live_complete(prompt, system)

    def _mock_complete(self, prompt: str, system: str | None) -> str:
        gist = mock_hash_summary(prompt)
        return (
            f"[mock-groq] Security review: {gist} "
            f"— treat as a real finding pending manual confirmation."
        )

    def _live_complete(self, prompt: str, system: str | None) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 512,
            "temperature": 0.2,
        }
        attempts = self.max_retries + 1
        last_error = "unknown error"

        for attempt in range(attempts):
            try:
                resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
            except requests.RequestException as exc:
                last_error = f"request failed: {exc}"
                if attempt < attempts - 1:
                    time.sleep(min(float(2 ** attempt), MAX_BACKOFF_SECONDS))
                    continue
                raise ProviderUnavailable("groq", f"{last_error} after {attempts} attempt(s)") from exc

            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = f"{resp.status_code}: {resp.text[:300]}"
                if attempt < attempts - 1:
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        wait_s = float(retry_after) if retry_after else min(float(2 ** attempt), MAX_BACKOFF_SECONDS)
                    except ValueError:
                        wait_s = min(float(2 ** attempt), MAX_BACKOFF_SECONDS)
                    time.sleep(wait_s)
                    continue
                raise ProviderUnavailable(
                    "groq",
                    f"unavailable after {attempts} attempt(s): {last_error}",
                    kind="quota" if resp.status_code == 429 else "capacity",
                )

            if resp.status_code >= 400:
                # Auth failures, malformed requests, unknown model: retrying
                # or switching providers won't help, so fail fast and loudly.
                raise RuntimeError(f"Groq API request failed ({resp.status_code}): {resp.text[:300]}")

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return ""
            return (choices[0].get("message", {}).get("content") or "").strip()

        raise ProviderUnavailable("groq", f"failed after {attempts} attempt(s): {last_error}")
