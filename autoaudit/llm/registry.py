"""Provider registry: the single place LLM providers are constructed and
looked up. Agents and the API never construct GroqClient/GeminiClient
directly — they ask the registry for "whatever provider this agent is
configured to use", so adding a new provider (OpenRouter, Anthropic,
Ollama, ...) means writing one LLMClient subclass and adding one line
here — no agent code changes, satisfying the "reusable provider interface,
future providers pluggable" requirement.

Per-agent provider selection is config-driven (see Config.security_agent_provider
etc.), not hardcoded — "each agent should be configurable to use any
supported provider".
"""
from __future__ import annotations

from ..config import Config
from .base import LLMClient, ProviderHealth
from .gemini_client import GeminiClient
from .groq_client import GroqClient

# Primary/secondary designation per the project spec: Gemini 2.5 Flash is
# the primary provider (default for any agent without an explicit
# override); Groq (Llama 3.3 70B) is the secondary provider (used as the
# configured choice for agents that specifically want it, and as the
# automatic-failover target when the primary is unhealthy/erroring).
PRIMARY_PROVIDER = "gemini"
SECONDARY_PROVIDER = "groq"


class ProviderRegistry:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._factories = {
            "gemini": lambda: GeminiClient(
                api_key=config.gemini_api_key or "", model=config.gemini_model, mock=not config.is_live(),
                request_delay_ms=config.gemini_request_delay_ms, max_retries=config.gemini_max_retries,
                thinking_budget=config.gemini_thinking_budget,
                thinking_level=config.gemini_thinking_level,
                max_output_tokens=config.gemini_max_output_tokens,
                http_timeout_seconds=config.gemini_http_timeout_seconds,
            ),
            "groq": lambda: GroqClient(
                api_key=config.groq_api_key or "", model=config.groq_model, mock=not config.is_live(),
            ),
        }
        self._instances: dict[str, LLMClient] = {}

    def register(self, name: str, factory) -> None:
        """Add a new provider without touching any agent code — e.g.
        `registry.register("openrouter", lambda: OpenRouterClient(...))`.
        """
        self._factories[name] = factory
        self._instances.pop(name, None)

    def available_providers(self) -> list[str]:
        return list(self._factories.keys())

    def get(self, name: str) -> LLMClient:
        if name not in self._factories:
            raise KeyError(f"Unknown provider {name!r}. Available: {self.available_providers()}")
        if name not in self._instances:
            self._instances[name] = self._factories[name]()
        return self._instances[name]

    def get_all(self) -> dict[str, LLMClient]:
        return {name: self.get(name) for name in self._factories}

    # ---- per-agent configured provider lookup -----------------------------

    def for_agent(self, agent_name: str) -> LLMClient:
        """Resolve the provider an agent should use: its own config
        override if set, else the system primary. This is the one place
        "which agent uses which provider" is decided — change
        `Config.<agent>_agent_provider` (env var) to reassign an agent to
        a different provider with zero code changes."""
        override = getattr(self.config, f"{agent_name}_agent_provider", None)
        provider_name = override or PRIMARY_PROVIDER
        return self.get(provider_name)

    # ---- health checks / automatic failover --------------------------------

    def health_check(self, name: str) -> ProviderHealth:
        return self.get(name).health_check()

    def health_check_all(self) -> dict[str, ProviderHealth]:
        return {name: self.health_check(name) for name in self._factories}

    def healthy_provider_order(self, preferred: str) -> list[str]:
        """Ordered provider names to try, `preferred` first, for automatic
        failover: skips providers known to be unhealthy as of the most
        recent check, falling back to trying everything if nothing checks
        out healthy (better to attempt and fail clearly than refuse to try)."""
        health = self.health_check_all()
        healthy = [n for n in self._factories if health.get(n) and health[n].healthy]
        order = [preferred] + [n for n in self._factories if n != preferred]
        if healthy:
            order = [n for n in order if n in healthy] + [n for n in order if n not in healthy]
        return order