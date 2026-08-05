"""Claude client — powers the Security Agent (careful, high-precision
interpretation of static-analysis evidence)."""
from __future__ import annotations

import requests

from .base import LLMClient, mock_hash_summary

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeClient(LLMClient):
    provider = "anthropic"

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-6", mock: bool = True) -> None:
        self.api_key = api_key
        self.model = model
        self.mock = mock or not api_key

    def complete(self, prompt: str, system: str | None = None) -> str:
        if self.mock:
            return self._mock_complete(prompt, system)
        return self._live_complete(prompt, system)

    def _mock_complete(self, prompt: str, system: str | None) -> str:
        gist = mock_hash_summary(prompt)
        return (
            f"[mock-claude] Security review: {gist} "
            f"— treat as a real finding pending manual confirmation."
        )

    def _live_complete(self, prompt: str, system: str | None) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        payload: dict = {
            "model": self.model,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        resp = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        return "\n".join(parts).strip()
