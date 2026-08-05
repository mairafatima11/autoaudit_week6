from __future__ import annotations

from pathlib import Path

from autoaudit.config import Config
from autoaudit.llm.base import LLMClient, ProviderHealth
from autoaudit.llm.registry import PRIMARY_PROVIDER, SECONDARY_PROVIDER, ProviderRegistry


def _mock_config(tmp_path: Path, **overrides) -> Config:
    return Config(
        mode="mock", groq_api_key=None, gemini_api_key=None,
        data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
        **overrides,
    )


def test_registry_has_gemini_and_groq_by_default(tmp_path: Path):
    registry = ProviderRegistry(_mock_config(tmp_path))
    assert set(registry.available_providers()) == {"gemini", "groq"}


def test_primary_and_secondary_designation():
    assert PRIMARY_PROVIDER == "gemini"
    assert SECONDARY_PROVIDER == "groq"


def test_get_returns_same_instance_on_repeat_calls(tmp_path: Path):
    registry = ProviderRegistry(_mock_config(tmp_path))
    a = registry.get("gemini")
    b = registry.get("gemini")
    assert a is b


def test_get_unknown_provider_raises(tmp_path: Path):
    registry = ProviderRegistry(_mock_config(tmp_path))
    try:
        registry.get("nonexistent")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_register_new_provider_without_touching_agent_code(tmp_path: Path):
    """Simulates adding OpenRouter/Anthropic/Ollama: one register() call,
    no changes anywhere else."""

    class FakeProvider(LLMClient):
        provider = "fake"

        def complete(self, prompt: str, system: str | None = None) -> str:
            return "fake response"

    registry = ProviderRegistry(_mock_config(tmp_path))
    registry.register("fake", lambda: FakeProvider())

    assert "fake" in registry.available_providers()
    client = registry.get("fake")
    assert client.complete("hi") == "fake response"


def test_for_agent_uses_configured_provider(tmp_path: Path):
    config = _mock_config(tmp_path, security_agent_provider="gemini")
    registry = ProviderRegistry(config)
    assert registry.for_agent("security").provider == "gemini"


def test_for_agent_falls_back_to_primary_when_unset(tmp_path: Path):
    config = _mock_config(tmp_path)
    registry = ProviderRegistry(config)
    # "unknown_agent" has no corresponding config field at all -> getattr's
    # default (None) kicks in -> falls back to the system primary.
    assert registry.for_agent("unknown_agent").provider == PRIMARY_PROVIDER


def test_default_per_agent_provider_assignment(tmp_path: Path):
    """Locks in the documented default assignment: precision-sensitive
    agents (security/fix) on Groq, higher-volume agents (quality/doc) on
    Gemini — each independently overridable via env/config."""
    config = _mock_config(tmp_path)
    registry = ProviderRegistry(config)
    assert registry.for_agent("security").provider == "groq"
    assert registry.for_agent("fix").provider == "groq"
    assert registry.for_agent("quality").provider == "gemini"
    assert registry.for_agent("documentation").provider == "gemini"


def test_env_var_overrides_agent_provider(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SECURITY_AGENT_PROVIDER", "gemini")
    config = Config(mode="mock", data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    assert config.security_agent_provider == "gemini"
    registry = ProviderRegistry(config)
    assert registry.for_agent("security").provider == "gemini"


def test_health_check_all_reports_healthy_in_mock_mode(tmp_path: Path):
    registry = ProviderRegistry(_mock_config(tmp_path))
    results = registry.health_check_all()
    assert set(results.keys()) == {"gemini", "groq"}
    for health in results.values():
        assert isinstance(health, ProviderHealth)
        assert health.healthy is True
        assert health.latency_ms >= 0


def test_healthy_provider_order_prefers_requested_provider_when_all_healthy(tmp_path: Path):
    registry = ProviderRegistry(_mock_config(tmp_path))
    order = registry.healthy_provider_order(preferred="groq")
    assert order[0] == "groq"
    assert set(order) == {"gemini", "groq"}


def test_healthy_provider_order_deprioritizes_unhealthy_provider(tmp_path: Path):
    class AlwaysDownClient(LLMClient):
        provider = "groq"

        def complete(self, prompt: str, system: str | None = None) -> str:
            raise RuntimeError("simulated outage")

    registry = ProviderRegistry(_mock_config(tmp_path))
    registry._instances["groq"] = AlwaysDownClient()  # force groq to appear unhealthy

    order = registry.healthy_provider_order(preferred="groq")
    # groq is unhealthy, so even though it was "preferred", it should be
    # pushed behind the healthy gemini provider — this is the automatic
    # failover behavior.
    assert order[0] == "gemini"
    assert order[-1] == "groq"
