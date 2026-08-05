"""Provider-outage behaviour.

Reproduces the failure that killed a real ~400s Flask audit at its last
step:

    Gemini API server error after 4 attempt(s): 503 server error:
    "This model is currently experiencing high demand..."

Two distinct things were wrong. First, batching/spacing/retry — all of
which address HTTP 429, i.e. *our* request rate — cannot fix a 503, which
is the provider's own capacity and is identical however slowly we ask.
The remedy for 503 is a different provider, and the project already had a
`ModelRouter` with Gemini->Groq failover; the Quality and Documentation
agents just weren't using it (they reached past it into `router.clients`,
or held a bare client). Second, any drafting failure propagated out of
`Supervisor.run()` and destroyed the entire run, including the repository
indexing, security scan and quality analysis that had already succeeded.
"""
from __future__ import annotations

import time

import pytest
import requests

from autoaudit.agents.documentation_agent import DocumentationAgent
from autoaudit.agents.quality_agent import QualityAgent
from autoaudit.agents.repository_agent import RepositoryAgent
from autoaudit.llm.base import LLMClient, ProviderUnavailable
from autoaudit.llm.gemini_client import GeminiClient
from autoaudit.llm.groq_client import GroqClient
from autoaudit.llm.router import ModelRouter, RouterConfig
from autoaudit.memory.vector_store import VectorStore
from autoaudit.tracing import Tracer


class _Response:
    """Minimal stand-in for `requests.Response`."""

    def __init__(self, status_code: int, text: str = "{}", headers: dict | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self):
        return {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "choices": [{"message": {"content": "ok"}}],
        }


HIGH_DEMAND_503 = (
    '{"error": {"code": 503, "message": "This model is currently experiencing '
    'high demand. Spikes in demand are usually temporary. Please try again '
    'later.", "status": "UNAVAILABLE"}}'
)


class _StubClient(LLMClient):
    """Test double that fails a configurable number of times."""

    def __init__(self, provider: str, *, fail_with: Exception | None = None, response: str = "drafted"):
        self.provider = provider
        self.model = f"{provider}-test"
        self.mock = False
        self.fail_with = fail_with
        self.response = response
        self.calls = 0

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return self.response


def _fast_router(clients) -> ModelRouter:
    return ModelRouter(clients, RouterConfig(retry_backoff_seconds=0.0, timeout_seconds=10.0))


# --- client-level classification -------------------------------------------


def test_gemini_503_raises_provider_unavailable_not_a_bare_error(monkeypatch):
    """A 503 must be classified so the router knows to fail over."""
    client = GeminiClient(api_key="k", mock=False, request_delay_ms=0, max_retries=1)
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response(503, HIGH_DEMAND_503))

    with pytest.raises(ProviderUnavailable) as exc:
        client.complete("hello")
    assert exc.value.provider == "gemini"
    # 503 is the provider's capacity, not our request rate.
    assert exc.value.kind == "capacity"
    # The message must not send the user off tuning batch size, which is
    # the fix for 429 and does nothing here.
    assert "will not help" in str(exc.value)


def test_gemini_429_is_classified_as_a_quota_problem(monkeypatch):
    """429 is our own request rate — spacing and batch size genuinely do
    help, so the guidance differs from the 503 case."""
    client = GeminiClient(api_key="k", mock=False, request_delay_ms=0, max_retries=0)
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response(429, "rate limited"))

    with pytest.raises(ProviderUnavailable) as exc:
        client.complete("hello")
    assert exc.value.kind == "quota"
    assert "GEMINI_REQUEST_DELAY_MS" in str(exc.value)


def test_gemini_400_still_fails_fast_without_failover(monkeypatch):
    """A malformed request or bad key isn't fixed by another provider."""
    client = GeminiClient(api_key="k", mock=False, request_delay_ms=0, max_retries=2)
    calls = []

    def _post(*a, **k):
        calls.append(1)
        return _Response(400, "bad request")

    monkeypatch.setattr(requests, "post", _post)
    with pytest.raises(RuntimeError) as exc:
        client.complete("hello")
    assert not isinstance(exc.value, ProviderUnavailable)
    assert len(calls) == 1, "4xx must not be retried"


def test_groq_retries_then_reports_unavailable(monkeypatch):
    """Groq is the failover target, so it needs its own resilience — it
    previously issued one un-retried request and raised a raw HTTPError."""
    client = GroqClient(api_key="k", mock=False, max_retries=2)
    calls = []

    def _post(*a, **k):
        calls.append(1)
        return _Response(503, "overloaded")

    monkeypatch.setattr(requests, "post", _post)
    monkeypatch.setattr("autoaudit.llm.groq_client.time.sleep", lambda *_: None)

    with pytest.raises(ProviderUnavailable):
        client.complete("hello")
    assert len(calls) == 3, "should retry up to max_retries before giving up"


def test_groq_recovers_when_a_retry_succeeds(monkeypatch):
    client = GroqClient(api_key="k", mock=False, max_retries=3)
    responses = [_Response(503, "overloaded"), _Response(200)]
    monkeypatch.setattr(requests, "post", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr("autoaudit.llm.groq_client.time.sleep", lambda *_: None)

    assert client.complete("hello") == "ok"


# --- router-level failover --------------------------------------------------


def test_router_fails_over_to_the_secondary_provider_on_503():
    down = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503 high demand"))
    up = _StubClient("groq", response="drafted by groq")
    router = _fast_router({"gemini": down, "groq": up})

    result = router.complete("prompt", profile="cheap")
    assert result.error is None
    assert result.provider == "groq"
    assert result.response == "drafted by groq"


@pytest.mark.parametrize("kind", ["capacity", "quota"])
def test_router_does_not_burn_retries_on_a_saturated_provider(kind):
    """The client already exhausted its backoff before raising. Retrying it
    at the router level only delays the failover that actually works."""
    down = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503", kind=kind))
    up = _StubClient("groq")
    router = _fast_router({"gemini": down, "groq": up})

    router.complete("prompt", profile="cheap")
    assert down.calls == 1, f"expected a single attempt before failover, got {down.calls}"


def test_router_still_retries_a_transient_error_before_failing_over():
    """Generic errors keep the old retry behaviour — only the explicit
    'provider is saturated' signal short-circuits."""
    flaky = _StubClient("gemini", fail_with=RuntimeError("connection reset"))
    router = _fast_router({"gemini": flaky, "groq": _StubClient("groq")})

    router.complete("prompt", profile="cheap")
    assert flaky.calls == RouterConfig().max_retries + 1


def test_router_reports_an_error_when_every_provider_is_down():
    router = _fast_router({
        "gemini": _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503")),
        "groq": _StubClient("groq", fail_with=ProviderUnavailable("groq", "503")),
    })
    result = router.complete("prompt", profile="cheap")
    assert result.error is not None


def test_complete_text_returns_text_or_error_never_both():
    ok = _fast_router({"gemini": _StubClient("gemini", response="hi")})
    text, error = ok.complete_text("p")
    assert text == "hi" and error is None

    bad = _fast_router({"gemini": _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503"))})
    text, error = bad.complete_text("p")
    assert text is None and error is not None


# --- circuit breaker --------------------------------------------------------


def test_breaker_stops_re_asking_a_provider_that_just_said_it_is_down():
    """Every subsequent call would otherwise pay another full retry/backoff
    cycle to learn what the first call already established."""
    down = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503"))
    up = _StubClient("groq")
    router = _fast_router({"gemini": down, "groq": up})

    for _ in range(10):
        assert router.complete("prompt", profile="cheap").error is None
    assert down.calls == 1, f"gemini re-asked {down.calls} times while cooling down"
    assert up.calls == 10


def test_breaker_returns_immediately_when_every_provider_is_down():
    down_a = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503"))
    down_b = _StubClient("groq", fail_with=ProviderUnavailable("groq", "503"))
    router = _fast_router({"gemini": down_a, "groq": down_b})

    assert router.complete("first", profile="cheap").error is not None
    for _ in range(20):
        assert router.complete("later", profile="cheap").error is not None
    # One attempt each on the first call; everything after is short-circuited.
    assert down_a.calls == 1 and down_b.calls == 1


def test_breaker_expires_so_a_brief_spike_does_not_sideline_a_provider():
    down = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503"))
    router = ModelRouter(
        {"gemini": down},
        RouterConfig(retry_backoff_seconds=0.0, unavailable_cooldown_seconds=0.05),
    )
    assert router.complete("p", profile="cheap").error is not None
    time.sleep(0.08)
    down.fail_with = None
    assert router.complete("p", profile="cheap").error is None


def test_breaker_resets_after_a_success():
    flaky = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503"))
    router = _fast_router({"gemini": flaky, "groq": _StubClient("groq")})
    router.complete("p", profile="cheap")

    flaky.fail_with = None
    router._reset_breaker("gemini")
    result = router.complete("p", profile="cheap")
    assert result.provider == "gemini" and result.error is None


def test_router_timeout_exceeds_the_clients_own_retry_budget():
    """A 30s router budget (the old default) would kill batched drafting
    calls that were still legitimately in progress, since the clients use a
    60s per-request timeout with several backoff retries."""
    assert RouterConfig().timeout_seconds > 60


# --- agent-level degradation ------------------------------------------------


def _kb(tmp_path, mock_repo_path):
    tracer = Tracer("failover_run", tmp_path / "logs")
    store = VectorStore(tmp_path / "vs.db")
    repo_id, files, _tmp, _root = RepositoryAgent(store, tracer).build_knowledge_base(mock_repo_path)
    return store, tracer, repo_id, files


def test_quality_agent_fails_over_rather_than_raising(tmp_path, mock_repo_path):
    store, tracer, repo_id, files = _kb(tmp_path, mock_repo_path)
    down = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503 high demand"))
    up = _StubClient("groq", response="phrased by the fallback provider")
    agent = QualityAgent(
        down, store, tracer, router=_fast_router({"gemini": down, "groq": up}), provider="gemini",
    )
    try:
        findings = agent.run(repo_id, files)
        assert findings, "findings must survive a primary-provider outage"
        assert agent.degraded_count == 0, "failover succeeded, so nothing should be degraded"
        assert any("fallback provider" in f.description for f in findings)
    finally:
        store.close()


def test_quality_agent_degrades_instead_of_killing_the_run(tmp_path, mock_repo_path):
    """With every provider down, findings keep their heuristic description
    rather than the whole audit being lost."""
    store, tracer, repo_id, files = _kb(tmp_path, mock_repo_path)
    down_a = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503"))
    down_b = _StubClient("groq", fail_with=ProviderUnavailable("groq", "503"))
    agent = QualityAgent(
        down_a, store, tracer, router=_fast_router({"gemini": down_a, "groq": down_b}), provider="gemini",
    )
    try:
        findings = agent.run(repo_id, files)
        assert findings, "a total provider outage must not lose the findings"
        assert agent.degraded_count == len(findings)
        # Detection is deterministic, so these are still fully trustworthy.
        for f in findings:
            assert f.file and f.rule and f.severity
            assert f.description.strip()
    finally:
        store.close()


def test_documentation_agent_degrades_instead_of_killing_the_run(tmp_path, mock_repo_path):
    _store, tracer, _repo_id, files = _kb(tmp_path, mock_repo_path)
    down_a = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503"))
    down_b = _StubClient("groq", fail_with=ProviderUnavailable("groq", "503"))
    agent = DocumentationAgent(_fast_router({"gemini": down_a, "groq": down_b}), tracer, provider="gemini")

    suggestions = agent.run(files)
    assert suggestions, "doc gaps must survive a total provider outage"
    assert agent.degraded_count == len(suggestions)
    for s in suggestions:
        assert s.file and s.kind
        assert "not drafted" in s.suggestion


def test_documentation_agent_does_not_hammer_a_down_provider(tmp_path, mock_repo_path):
    """Retrying a failed batch item-by-item against an endpoint that just
    said it can't serve us means N more full backoff cycles — hundreds of
    doomed requests on a repo the size of Flask."""
    _store, tracer, _repo_id, files = _kb(tmp_path, mock_repo_path)
    down_a = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503"))
    down_b = _StubClient("groq", fail_with=ProviderUnavailable("groq", "503"))
    agent = DocumentationAgent(
        _fast_router({"gemini": down_a, "groq": down_b}), tracer, provider="gemini", batch_size=8,
    )
    suggestions = agent.run(files)

    batches = -(-len(suggestions) // 8)  # ceil
    # One attempt per provider per batch — not one per suggestion.
    assert down_a.calls <= batches, f"{down_a.calls} calls for {batches} batches"
    assert down_b.calls <= batches


def test_documentation_agent_architecture_explanation_degrades(tmp_path, mock_repo_path):
    _store, tracer, _repo_id, files = _kb(tmp_path, mock_repo_path)
    down = _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503"))
    agent = DocumentationAgent(_fast_router({"gemini": down}), tracer, provider="gemini")

    explanation = agent.generate_architecture_explanation(files)
    assert explanation, "must fall back to the structural digest, not raise"
    assert "unavailable" in explanation.lower()


def test_full_run_survives_a_primary_provider_outage(tmp_path, mock_repo_path, monkeypatch):
    """End-to-end: the exact shape of the reported failure. A Gemini 503
    during drafting used to abort `Supervisor.run()` after minutes of work."""
    from autoaudit.agents.supervisor import Supervisor
    from autoaudit.config import Config
    from autoaudit.llm import registry as registry_module

    config = Config(
        mode="live", groq_api_key="groq-key", gemini_api_key="gemini-key",
        data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
    )

    real_init = registry_module.ProviderRegistry.__init__

    def patched_init(self, cfg):
        real_init(self, cfg)
        self._factories = {
            "gemini": lambda: _StubClient("gemini", fail_with=ProviderUnavailable("gemini", "503 high demand")),
            "groq": lambda: _StubClient("groq", response="drafted by groq"),
        }

    monkeypatch.setattr(registry_module.ProviderRegistry, "__init__", patched_init)

    report = Supervisor(config).run(mock_repo_path)

    assert report.findings, "the run must complete with its findings intact"
    assert report.files_scanned > 0
    assert report.chunks_indexed > 0
    assert report.degraded_suggestions == 0, "Groq was healthy, so nothing should degrade"
