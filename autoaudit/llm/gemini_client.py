"""Gemini client — powers the Quality Agent (cheaper/faster, higher-volume
reasoning across many files)."""
from __future__ import annotations

import requests

from .base import LLMClient, mock_hash_summary

GEMINI_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(self, api_key: str = "", model: str = "gemini-2.5-flash", mock: bool = True) -> None:
        self.api_key = api_key
        self.model = model
        self.mock = mock or not api_key

    def complete(self, prompt: str, system: str | None = None) -> str:
        if self.mock:
            return self._mock_complete(prompt, system)
        return self._live_complete(prompt, system)

    def _mock_complete(self, prompt: str, system: str | None) -> str:
        gist = mock_hash_summary(prompt)
        return f"[mock-gemini] Quality note: {gist}"

    def _live_complete(self, prompt: str, system: str | None) -> str:
        url = GEMINI_URL_TMPL.format(model=self.model)
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
        resp = requests.post(url, params={"key": self.api_key}, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "\n".join(p.get("text", "") for p in parts).strip()
