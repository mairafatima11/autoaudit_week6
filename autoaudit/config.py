"""Environment/config loading for AutoAudit AI.

Centralizing this avoids `os.environ` reads scattered across the codebase
and gives us one place to enforce "live mode requires a real key" instead
of silently downgrading to mock mode (see prompts.md, entry 12).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  
    pass


class ConfigError(RuntimeError):
    """Raised when configuration is invalid (e.g. live mode without a key)."""


@dataclass
class Config:
    mode: str = field(default_factory=lambda: os.getenv("AUTOAUDIT_MODE", "mock").lower())

    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None)
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"))

    gemini_api_key: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or None)
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    data_dir: Path = field(default_factory=lambda: Path(os.getenv("AUTOAUDIT_DATA_DIR", "./data")))
    log_dir: Path = field(default_factory=lambda: Path(os.getenv("AUTOAUDIT_LOG_DIR", "./logs")))

    max_file_bytes: int = 400_000
    embedding_dim: int = 256
    long_function_line_threshold: int = 40

    def __post_init__(self) -> None:
        if self.mode not in ("mock", "live"):
            raise ConfigError(f"AUTOAUDIT_MODE must be 'mock' or 'live', got {self.mode!r}")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def is_live(self) -> bool:
        return self.mode == "live"

    def require_key(self, provider: str) -> str:
        """Return the API key for `provider`, raising if live mode lacks one."""
        key = self.anthropic_api_key if provider == "anthropic" else self.gemini_api_key
        if self.is_live() and not key:
            raise ConfigError(
                f"AUTOAUDIT_MODE=live but no API key configured for {provider!r}. "
                f"Set it in .env or export it, or switch AUTOAUDIT_MODE=mock."
            )
        return key or ""


def load_config() -> Config:
    return Config()
