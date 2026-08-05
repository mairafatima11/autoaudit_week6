"""Gemini client — powers the Quality Agent (cheaper/faster, higher-volume
reasoning across many files).

Live requests go through two protections that did not exist before:

- **Rate limiting** (`GEMINI_REQUEST_DELAY_MS`, default 200ms): every live
  request is spaced at least this many milliseconds apart from the previous
  one. A single `GeminiClient` instance is shared (via `ProviderRegistry`)
  by every agent that uses Gemini, and the Quality/Documentation agents run
  concurrently in separate threads, so the delay is enforced with a lock
  around a shared "last request time" — concurrent callers queue up rather
  than bursting the API at once.
- **Retry with exponential backoff on HTTP 429** (`GEMINI_MAX_RETRIES`,
  default 3): a rate-limited request is retried with backoff (honoring the
  API's `Retry-After` header when present) instead of raising immediately.
  Other client/server errors get a shorter, best-effort retry for transient
  5xx responses; anything else fails fast with a clear message instead of
  a raw `requests.HTTPError` traceback.
"""
from __future__ import annotations

import os
import re
import threading
import time

import requests

from .base import LLMClient, ProviderUnavailable, mock_hash_summary

GEMINI_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

DEFAULT_REQUEST_DELAY_MS = 200
DEFAULT_MAX_RETRIES = 3
MAX_BACKOFF_SECONDS = 30.0
DEFAULT_HTTP_TIMEOUT_SECONDS = 90.0

# Gemini's reasoning controls changed shape between model generations, and
# sending the wrong generation's parameters is not harmless.
#
# **2.x** — thinking is controlled by an integer token budget nested under
# `generationConfig.thinkingConfig.thinkingBudget`. On 2.5 Flash thinking is
# ON by default; `0` disables it. `temperature` is supported and useful.
#
# **3.x** (3.5 Flash-Lite, 3.6 Flash, ...) — thinking is controlled by a
# string enum `thinkingLevel` (`minimal` | `low` | `medium` | `high`), and:
#
#   - `thinkingBudget` is legacy. Sending BOTH it and `thinkingLevel` in one
#     request is a documented 400 error.
#   - `temperature`, `topP` and `topK` are **deprecated**: currently ignored,
#     and documented to return HTTP 400 in future model generations.
#   - Defaults differ per model — `gemini-3.5-flash-lite` already defaults to
#     `minimal`, the lowest setting, so there is no thinking overhead to
#     remove there in the first place.
#
# See docs/ARCHITECTURE.md for why this distinction earned its own constant.
DEFAULT_THINKING_BUDGET = 0            # 2.x only
DEFAULT_THINKING_LEVEL = "minimal"     # 3.x only
_VALID_THINKING_LEVELS = ("minimal", "low", "medium", "high")
# Generous enough for a batch of 8 short items plus their ###ITEM n###
# markers, without letting a confused model generate indefinitely.
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.2              # 2.x only; deprecated on 3.x


def _is_gemini_3_or_newer(model: str) -> bool:
    """True for `gemini-3*` and later families.

    Deliberately a prefix check on the major version rather than a hardcoded
    model list: new models ship faster than this file changes, and the
    failure mode of treating a *newer* model as 3.x-style is far milder than
    sending it deprecated 2.x sampling parameters.
    """
    name = (model or "").strip().lower()
    match = re.match(r"gemini-(\d+)", name)
    return bool(match) and int(match.group(1)) >= 3


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(
        self,
        api_key: str = "",
        model: str = "gemini-2.5-flash",
        mock: bool = True,
        request_delay_ms: int | None = None,
        max_retries: int | None = None,
        thinking_budget: int | None = None,
        max_output_tokens: int | None = None,
        http_timeout_seconds: float | None = None,
        thinking_level: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.mock = mock or not api_key
        self.thinking_budget = (
            thinking_budget
            if thinking_budget is not None
            else int(os.getenv("GEMINI_THINKING_BUDGET", str(DEFAULT_THINKING_BUDGET)))
        )
        self.max_output_tokens = (
            max_output_tokens
            if max_output_tokens is not None
            else int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)))
        )
        self.http_timeout_seconds = (
            http_timeout_seconds
            if http_timeout_seconds is not None
            else float(os.getenv("GEMINI_HTTP_TIMEOUT_SECONDS", str(DEFAULT_HTTP_TIMEOUT_SECONDS)))
        )
        self.thinking_level = (
            thinking_level
            if thinking_level is not None
            else os.getenv("GEMINI_THINKING_LEVEL", DEFAULT_THINKING_LEVEL)
        ).strip().lower()
        if self.thinking_level not in _VALID_THINKING_LEVELS:
            self.thinking_level = DEFAULT_THINKING_LEVEL
        self.is_gemini_3 = _is_gemini_3_or_newer(self.model)
        # Flipped to False if the model rejects the thinking field, so we stop
        # sending it instead of failing every request on an unsupported model.
        self._thinking_supported = True

        # Configurable via constructor arg (preferred — see
        # ProviderRegistry, which threads Config values through) or, as a
        # fallback for anyone constructing GeminiClient directly, via
        # environment variables.
        self.request_delay_ms = (
            request_delay_ms
            if request_delay_ms is not None
            else int(os.getenv("GEMINI_REQUEST_DELAY_MS", str(DEFAULT_REQUEST_DELAY_MS)))
        )
        self.max_retries = (
            max_retries
            if max_retries is not None
            else int(os.getenv("GEMINI_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))
        )

        # Shared across threads calling this same instance (the registry
        # hands out one GeminiClient per process), so the rate limit is
        # enforced globally for this client, not per-caller.
        self._rate_lock = threading.Lock()
        self._last_request_at: float = 0.0

    def complete(self, prompt: str, system: str | None = None) -> str:
        if self.mock:
            return self._mock_complete(prompt, system)
        return self._live_complete(prompt, system)

    def _mock_complete(self, prompt: str, system: str | None) -> str:
        gist = mock_hash_summary(prompt)
        return f"[mock-gemini] Quality note: {gist}"

    # ---- rate limiting -------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Block until at least `request_delay_ms` has elapsed since the
        last live request made by this client instance."""
        if self.request_delay_ms <= 0:
            return
        with self._rate_lock:
            now = time.monotonic()
            elapsed_ms = (now - self._last_request_at) * 1000
            remaining_ms = self.request_delay_ms - elapsed_ms
            if remaining_ms > 0:
                time.sleep(remaining_ms / 1000)
            self._last_request_at = time.monotonic()

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        """Exponential backoff: 1s, 2s, 4s, 8s, ... capped."""
        return min(float(2 ** attempt), MAX_BACKOFF_SECONDS)

    @staticmethod
    def _retry_after_seconds(resp: requests.Response) -> float | None:
        header = resp.headers.get("Retry-After")
        if not header:
            return None
        try:
            return max(0.0, float(header))
        except ValueError:
            return None

    # ---- live request ----------------------------------------------------

    def _generation_config(self) -> dict:
        """Build a `generationConfig` valid for *this model's* generation.

        The two families are not interchangeable — see the constants above.
        Notably, sending 2.x's `thinkingBudget` alongside 3.x's
        `thinkingLevel` is a documented 400, and 3.x deprecates the sampling
        parameters entirely.
        """
        config: dict = {"maxOutputTokens": self.max_output_tokens}

        if self.is_gemini_3:
            # No temperature/topP/topK: deprecated on 3.x, ignored today and
            # documented to become a 400 in later model generations.
            if self._thinking_supported:
                config["thinking"] = {"thinkingLevel": self.thinking_level}
            return config

        config["temperature"] = DEFAULT_TEMPERATURE
        if self._thinking_supported and self.thinking_budget is not None:
            config["thinkingConfig"] = {"thinkingBudget": self.thinking_budget}
        return config

    @staticmethod
    def _extract_text(data: dict) -> tuple[str, str | None]:
        """Return `(text, problem)`.

        The previous version returned `""` for a response with no candidates
        or no parts, which is exactly what a thinking-enabled model produces
        when the whole output budget is consumed before it writes anything.
        That empty string flowed silently into findings as their description.
        Reporting the problem lets the caller retry or degrade visibly.
        """
        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback") or {}
            blocked = feedback.get("blockReason")
            return "", f"no candidates returned{f' (blocked: {blocked})' if blocked else ''}"

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "\n".join(p.get("text", "") for p in parts).strip()

        if not text:
            if finish_reason == "MAX_TOKENS":
                return "", (
                    "response hit maxOutputTokens before producing any text — "
                    "raise GEMINI_MAX_OUTPUT_TOKENS or lower the batch size"
                )
            return "", f"empty response (finishReason={finish_reason})"
        return text, None

    def _live_complete(self, prompt: str, system: str | None) -> str:
        url = GEMINI_URL_TMPL.format(model=self.model)
        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        attempts = self.max_retries + 1
        last_error: str = "unknown error"

        for attempt in range(attempts):
            self._wait_for_rate_limit()
            payload = {
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": self._generation_config(),
            }

            try:
                resp = requests.post(
                    url, params={"key": self.api_key}, json=payload,
                    timeout=self.http_timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = f"request failed: {exc}"
                if attempt < attempts - 1:
                    time.sleep(self._backoff_seconds(attempt))
                    continue
                raise RuntimeError(
                    f"Gemini request failed after {attempts} attempt(s): {last_error}"
                ) from exc

            if resp.status_code == 429:
                last_error = f"429 Too Many Requests: {resp.text[:300]}"
                if attempt < attempts - 1:
                    wait_s = self._retry_after_seconds(resp)
                    if wait_s is None:
                        wait_s = self._backoff_seconds(attempt)
                    time.sleep(wait_s)
                    continue
                # Raised as ProviderUnavailable, not a bare RuntimeError, so
                # ModelRouter can fail over to the other provider instead of
                # letting the whole run die. 429 is *our* quota: spacing
                # requests further apart genuinely helps here.
                raise ProviderUnavailable(
                    "gemini",
                    f"quota/rate limit exceeded after {attempts} attempt(s) (HTTP 429). "
                    f"This is your own request rate: raise GEMINI_REQUEST_DELAY_MS, "
                    f"lower the batch size, or check your quota tier. "
                    f"Last response: {resp.text[:300]}",
                    kind="quota",
                )

            if resp.status_code >= 500:
                last_error = f"{resp.status_code} server error: {resp.text[:300]}"
                if attempt < attempts - 1:
                    time.sleep(self._backoff_seconds(attempt))
                    continue
                # 5xx (notably 503 UNAVAILABLE, "this model is currently
                # experiencing high demand") is *Google's* capacity, not our
                # request rate — unlike 429, slowing down or batching harder
                # does not help, because the model is saturated for everyone.
                # The only real remedies are waiting or using a different
                # provider, so this is marked non-retryable against the same
                # provider and the router switches immediately.
                raise ProviderUnavailable(
                    "gemini",
                    f"server error after {attempts} attempt(s): {last_error}. "
                    f"HTTP 5xx is provider-side capacity, not your request rate — "
                    f"batching or spacing requests will not help; failing over "
                    f"to another provider.",
                    kind="capacity",
                )

            if resp.status_code >= 400:
                body = resp.text[:300]
                # A model can reject the thinking field for several reasons:
                # it doesn't support disabling thinking (2.5 Pro), or the
                # field name/shape differs for its generation. Drop it and
                # retry rather than failing every request — the cost is
                # latency, not correctness, and every model has a sane
                # default (e.g. 3.5 Flash-Lite already defaults to
                # `minimal`, which is what we'd have asked for anyway).
                if self._thinking_supported and "thinking" in body.lower():
                    self._thinking_supported = False
                    last_error = f"model rejected the thinking config: {body}"
                    continue
                # Other client errors (bad request, auth, unknown model)
                # won't be fixed by retrying — fail fast with a clear message.
                raise RuntimeError(f"Gemini API request failed ({resp.status_code}): {body}")

            text, problem = self._extract_text(resp.json())
            if problem is None:
                return text

            # An empty/truncated response is a real failure, not an empty
            # answer. Retry, then surface it so the caller degrades visibly
            # instead of writing "" into a finding's description.
            last_error = problem
            if attempt < attempts - 1:
                time.sleep(self._backoff_seconds(attempt))
                continue
            raise ProviderUnavailable(
                "gemini", f"{problem} (after {attempts} attempt(s))", kind="capacity"
            )

        # Unreachable in practice (every branch above returns or raises),
        # but keeps type-checkers/lints happy and fails loudly if it ever is.
        raise RuntimeError(f"Gemini request failed after {attempts} attempt(s): {last_error}")