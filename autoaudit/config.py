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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    mode: str = field(default_factory=lambda: os.getenv("AUTOAUDIT_MODE", "mock").lower())

    groq_api_key: str | None = field(default_factory=lambda: os.getenv("GROQ_API_KEY") or None)
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))

    gemini_api_key: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or None)
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    # Rate limiting / retry for live Gemini requests (see llm/gemini_client.py).
    # Quality/Documentation agents previously issued one Gemini request per
    # finding/symbol with zero spacing between them, which exhausted the
    # free-tier quota (HTTP 429) well before a single ad-hoc request would.
    gemini_request_delay_ms: int = field(
        default_factory=lambda: int(os.getenv("GEMINI_REQUEST_DELAY_MS", "200"))
    )
    gemini_max_retries: int = field(default_factory=lambda: int(os.getenv("GEMINI_MAX_RETRIES", "3")))

    # Thinking controls, which differ by model generation (see
    # llm/gemini_client.py). 2.x uses an integer `thinkingBudget`; 3.x uses a
    # `thinkingLevel` string enum and deprecates the sampling parameters.
    # The client picks the right one from the model name — both are exposed
    # so either family can be tuned without code changes.
    gemini_thinking_budget: int = field(
        default_factory=lambda: int(os.getenv("GEMINI_THINKING_BUDGET", "0"))
    )
    # minimal | low | medium | high. `minimal` is already the default for
    # gemini-3.5-flash-lite; raise it only for work that needs real reasoning.
    gemini_thinking_level: str = field(
        default_factory=lambda: os.getenv("GEMINI_THINKING_LEVEL", "minimal")
    )
    # Bounds response length. Must stay comfortably above what a full batch
    # of items needs, or the response is truncated mid-batch and can't be
    # split back apart (which then costs per-item retries).
    gemini_max_output_tokens: int = field(
        default_factory=lambda: int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "4096"))
    )
    gemini_http_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("GEMINI_HTTP_TIMEOUT_SECONDS", "90"))
    )

    # How many findings/symbols to fold into a single Gemini request instead
    # of one request each. Applies only to live mode — mock mode has no
    # network cost, so it keeps phrasing one item at a time for simplicity.
    quality_agent_batch_size: int = field(
        default_factory=lambda: int(os.getenv("QUALITY_AGENT_BATCH_SIZE", "8"))
    )
    documentation_agent_batch_size: int = field(
        default_factory=lambda: int(os.getenv("DOCUMENTATION_AGENT_BATCH_SIZE", "8"))
    )
    # Security was the last agent still making one live request per finding.
    # That is the worst place to leave unbatched: `semgrep --config=auto`
    # can return hundreds of findings on a mid-sized repo, and every one of
    # them was a separate sequential round trip.
    security_agent_batch_size: int = field(
        default_factory=lambda: int(os.getenv("SECURITY_AGENT_BATCH_SIZE", "8"))
    )

    # Optional — enables real repository metadata (stars, forks, branch,
    # last commit, open issues) on the Repository Overview page. Without a
    # token, GitHub's API still works for public repos but at a much lower
    # unauthenticated rate limit (60 req/hour vs 5000).
    github_token: str | None = field(default_factory=lambda: os.getenv("GITHUB_TOKEN") or None)

    # Optional API-key auth placeholder (see api/auth.py). Unset by
    # default — the API is open, matching every prior milestone's
    # documented "no auth" limitation. Set AUTOAUDIT_API_KEY to require a
    # matching `Authorization: Bearer <key>` header on every /api/* route
    # except /api/health.
    api_key: str | None = field(default_factory=lambda: os.getenv("AUTOAUDIT_API_KEY") or None)

    # Per-agent provider overrides: "each agent should be configurable to
    # use any supported provider" without code changes. Unset -> the
    # ProviderRegistry falls back to the system primary (Gemini). Defaults
    # here preserve the considered design from earlier milestones (Security/
    # Fix agents on Groq for careful, high-precision reasoning; Quality/
    # Documentation on Gemini for higher-volume, lower-stakes work) while
    # making every one of those choices a one-line env var change.
    security_agent_provider: str = field(default_factory=lambda: os.getenv("SECURITY_AGENT_PROVIDER", "groq"))
    quality_agent_provider: str = field(default_factory=lambda: os.getenv("QUALITY_AGENT_PROVIDER", "gemini"))
    documentation_agent_provider: str = field(
        default_factory=lambda: os.getenv("DOCUMENTATION_AGENT_PROVIDER", "gemini")
    )
    fix_agent_provider: str = field(default_factory=lambda: os.getenv("FIX_AGENT_PROVIDER", "groq"))

    data_dir: Path = field(default_factory=lambda: Path(os.getenv("AUTOAUDIT_DATA_DIR", "./data")))
    log_dir: Path = field(default_factory=lambda: Path(os.getenv("AUTOAUDIT_LOG_DIR", "./logs")))

    max_file_bytes: int = 400_000
    embedding_dim: int = 256
    long_function_line_threshold: int = 40

    # Whether Documentation Agent's docstring/API-doc gap detection should
    # look inside test files (tests/, test_*.py, conftest.py). Off by
    # default — test helpers and fixtures are conventionally undocumented
    # in most Python codebases, so counting them as documentation gaps
    # mostly adds noise rather than signal. Set to true for codebases that
    # do expect docstrings on test helpers.
    documentation_include_tests: bool = field(
        default_factory=lambda: _env_bool("AUTOAUDIT_DOC_INCLUDE_TESTS", False)
    )
    # Whether to skip auto-generated Alembic migration files
    # (alembic/versions/*) when checking for missing docstrings/API docs.
    # On by default — these files are generated by `alembic revision` and
    # essentially never hand-documented in real projects.
    documentation_skip_generated_migrations: bool = field(
        default_factory=lambda: _env_bool("AUTOAUDIT_DOC_SKIP_MIGRATIONS", True)
    )

    # Minimum cosine-similarity score (against the hashing-based, non-
    # semantic embeddings this project intentionally uses — see
    # tools/embeddings.py) for two code chunks to be reported as possible
    # duplicates. Raised from the original 0.92 default because that
    # threshold was catching chunks that only share a handful of import
    # lines. Combined with the import-heavy-chunk filter in
    # QualityAgent._gather_duplicate_code, this is meant to preserve real
    # near-duplicate catches (e.g. copy-pasted CRUD routes) while dropping
    # import-only false positives. Tune per-repo if needed.
    quality_duplicate_min_score: float = field(
        default_factory=lambda: float(os.getenv("QUALITY_DUPLICATE_MIN_SCORE", "0.95"))
    )

    def __post_init__(self) -> None:
        if self.mode not in ("mock", "live"):
            raise ConfigError(f"AUTOAUDIT_MODE must be 'mock' or 'live', got {self.mode!r}")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def is_live(self) -> bool:
        return self.mode == "live"

    def require_key(self, provider: str) -> str:
        """Return the API key for `provider`, raising if live mode lacks one."""
        key = self.groq_api_key if provider == "groq" else self.gemini_api_key
        if self.is_live() and not key:
            raise ConfigError(
                f"AUTOAUDIT_MODE=live but no API key configured for {provider!r}. "
                f"Set it in .env or export it, or switch AUTOAUDIT_MODE=mock."
            )
        return key or ""


def load_config() -> Config:
    return Config()