"""Latency bounds for the endpoints a human waits on.

Two pages hung in real use: "Generate Fixes" and "Run Comparison". Neither
was an infinite loop — both were bounded, just at values indistinguishable
from a hang, and the bound didn't work anyway:

1. `RouterConfig.timeout_seconds` was raised to 240s to protect long batched
   *drafting* calls during an audit, but the same value governs interactive
   endpoints. 240s x 3 retries x 2 providers, plus `compare()`'s extra LLM
   judge call, put `/api/models/compare`'s worst case near 48 minutes.
2. `_call_with_timeout` ran its worker inside `with ThreadPoolExecutor(...)`,
   whose `__exit__` calls `shutdown(wait=True)`. The timeout therefore never
   bounded anything: the call ran to completion regardless and the caller
   waited the full duration before being handed a TimeoutError.
3. `FixAgent` resolved `router.clients[...]` and called the client directly,
   so no timeout, failover or circuit breaker applied at all — and it
   processed findings sequentially with no overall budget.
"""
from __future__ import annotations

import time

import pytest

from autoaudit.agents.fix_agent import FixAgent
from autoaudit.llm.base import LLMClient, ProviderUnavailable
from autoaudit.llm.router import ModelRouter, RouterConfig
from autoaudit.schemas import Category, Severity, make_finding
from autoaudit.tracing import Tracer


class _SlowClient(LLMClient):
    """Answers, but slowly — the 'provider is degraded' case a timeout exists
    to bound. Distinct from an outright failure, which is already covered."""

    def __init__(self, provider: str, delay: float, response: str = "response"):
        self.provider = provider
        self.model = f"{provider}-test"
        self.mock = False
        self.delay = delay
        self.response = response
        self.calls = 0

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls += 1
        time.sleep(self.delay)
        return self.response


def _finding(i: int):
    return make_finding(
        file=f"src/m{i}.py", line=i, category=Category.SECURITY, rule="dangerous-eval",
        title=f"Finding {i}", description="d", severity=Severity.HIGH,
        source_agent="security", source_tool="semgrep",
    )


# --- the timeout must actually bound the call -------------------------------


def test_timeout_actually_returns_early():
    """The context-managed executor blocked on shutdown, so a 1s budget
    against a 3s provider still cost the full 3s per attempt."""
    slow = _SlowClient("gemini", delay=3.0)
    router = ModelRouter(
        {"gemini": slow},
        RouterConfig(timeout_seconds=0.5, max_retries=0, retry_backoff_seconds=0.0),
    )

    start = time.monotonic()
    result = router.complete("p", profile="cheap")
    elapsed = time.monotonic() - start

    assert result.error is not None
    assert elapsed < 2.0, f"timeout did not bound the call: {elapsed:.1f}s for a 0.5s budget"


def test_retries_do_not_multiply_a_hang_past_the_budget():
    slow = _SlowClient("gemini", delay=3.0)
    router = ModelRouter(
        {"gemini": slow},
        RouterConfig(timeout_seconds=0.3, max_retries=2, retry_backoff_seconds=0.0),
    )

    start = time.monotonic()
    router.complete("p", profile="cheap")
    elapsed = time.monotonic() - start
    # 3 attempts x 0.3s, not 3 x 3s.
    assert elapsed < 2.0, f"{elapsed:.1f}s"


# --- interactive vs background budgets --------------------------------------


def test_interactive_budget_is_far_shorter_than_the_background_one():
    cfg = RouterConfig()
    assert cfg.interactive_timeout_seconds < cfg.timeout_seconds
    # A person should never wait minutes for a single provider call.
    assert cfg.interactive_timeout_seconds <= 60


def test_interactive_calls_use_the_short_budget():
    slow = _SlowClient("gemini", delay=2.0)
    router = ModelRouter(
        {"gemini": slow},
        RouterConfig(timeout_seconds=30.0, interactive_timeout_seconds=0.3,
                     max_retries=0, retry_backoff_seconds=0.0),
    )

    start = time.monotonic()
    result = router.complete("p", profile="cheap", interactive=True)
    assert result.error is not None
    assert time.monotonic() - start < 1.5, "interactive call used the background budget"


def test_background_calls_still_get_the_long_budget():
    """The short interactive budget must not leak into audit drafting,
    where multi-second batched calls are legitimate."""
    slow = _SlowClient("gemini", delay=0.5)
    router = ModelRouter(
        {"gemini": slow},
        RouterConfig(timeout_seconds=10.0, interactive_timeout_seconds=0.1,
                     max_retries=0, retry_backoff_seconds=0.0),
    )
    assert router.complete("p", profile="cheap").error is None


def test_compare_runs_on_the_interactive_budget():
    """`compare()` backs a page with a spinner on it."""
    slow_a = _SlowClient("gemini", delay=2.0)
    slow_b = _SlowClient("groq", delay=2.0)
    router = ModelRouter(
        {"gemini": slow_a, "groq": slow_b},
        RouterConfig(timeout_seconds=60.0, interactive_timeout_seconds=0.3,
                     max_retries=0, retry_backoff_seconds=0.0),
    )

    start = time.monotonic()
    comparison = router.compare("p")
    elapsed = time.monotonic() - start

    assert elapsed < 3.0, f"compare took {elapsed:.1f}s despite a 0.3s interactive budget"
    assert all(r.error is not None for r in comparison.results)
    # Degrades to a readable result rather than raising.
    assert comparison.reasoning_summary


# --- deadlines across a batch -----------------------------------------------


def test_deadline_stops_a_batch_from_overrunning():
    slow = _SlowClient("gemini", delay=0.4)
    router = ModelRouter(
        {"gemini": slow},
        RouterConfig(timeout_seconds=5.0, max_retries=0, retry_backoff_seconds=0.0),
    )
    deadline = time.monotonic() + 0.5

    results = [router.complete("p", profile="cheap", deadline=deadline) for _ in range(5)]
    # Once the shared deadline passes, later calls return immediately.
    assert any(r.error is not None for r in results)
    assert slow.calls < 5, f"deadline ignored: {slow.calls} calls made"


# --- fix agent --------------------------------------------------------------


def test_propose_fixes_respects_its_wall_clock_budget(tmp_path):
    slow = _SlowClient("groq", delay=1.0, response="not json")
    router = ModelRouter(
        {"groq": slow},
        RouterConfig(timeout_seconds=5.0, interactive_timeout_seconds=5.0,
                     max_retries=0, retry_backoff_seconds=0.0),
    )
    agent = FixAgent(router, Tracer("fixes", tmp_path / "logs"), primary_provider="groq")

    start = time.monotonic()
    proposals = agent.propose_fixes([_finding(i) for i in range(12)], budget_seconds=2.0)
    elapsed = time.monotonic() - start

    assert elapsed < 12.0, f"batch ran {elapsed:.1f}s against a 2s budget"
    # Every requested finding still gets a proposal — the user must never be
    # handed a silently truncated list.
    assert len(proposals) == 12


def test_propose_fixes_returns_one_proposal_per_finding_in_order(tmp_path):
    """Concurrency must not reorder or drop results."""
    router = ModelRouter(
        {"groq": _SlowClient("groq", delay=0.01, response="nope")},
        RouterConfig(max_retries=0, retry_backoff_seconds=0.0),
    )
    agent = FixAgent(router, Tracer("fixes", tmp_path / "logs"), primary_provider="groq")

    findings = [_finding(i) for i in range(6)]
    proposals = agent.propose_fixes(findings, budget_seconds=30.0)

    assert [p.finding_fingerprint for p in proposals] == [f.fingerprint for f in findings]


def test_propose_fixes_survives_a_total_provider_outage(tmp_path):
    down = _SlowClient("groq", delay=0.0)
    down.complete = lambda *a, **k: (_ for _ in ()).throw(ProviderUnavailable("groq", "503"))
    router = ModelRouter({"groq": down}, RouterConfig(max_retries=0, retry_backoff_seconds=0.0))
    agent = FixAgent(router, Tracer("fixes", tmp_path / "logs"), primary_provider="groq")

    proposals = agent.propose_fixes([_finding(i) for i in range(3)], budget_seconds=10.0)

    assert len(proposals) == 3
    for p in proposals:
        # Deterministic fallbacks, clearly labelled as needing human review.
        assert "manual review required" in p.patch
        assert p.estimated_confidence < 0.5


def test_propose_fixes_goes_through_the_router(tmp_path):
    """Regression guard: calling `router.clients[...]` directly bypassed
    failover, the timeout and the circuit breaker."""
    down = _SlowClient("gemini", delay=0.0)
    down.complete = lambda *a, **k: (_ for _ in ()).throw(ProviderUnavailable("gemini", "503"))
    up = _SlowClient("groq", delay=0.0, response='{"finding_fingerprint": "x", "file": "src/m0.py",'
                                                 ' "patch": "--- a\\n+++ b\\n", "pr_title": "t",'
                                                 ' "pr_description": "d", "commit_message": "c",'
                                                 ' "suggested_unit_test": "u",'
                                                 ' "suggested_integration_test": "i",'
                                                 ' "estimated_impact": "low",'
                                                 ' "estimated_confidence": 0.8}')
    router = ModelRouter({"gemini": down, "groq": up}, RouterConfig(max_retries=0, retry_backoff_seconds=0.0))
    agent = FixAgent(router, Tracer("fixes", tmp_path / "logs"), primary_provider="gemini")

    proposals = agent.propose_fixes([_finding(0)], budget_seconds=10.0)
    assert up.calls >= 1, "never failed over to the healthy provider"
    assert "manual review required" not in proposals[0].patch


@pytest.mark.parametrize("max_findings", [1, 3])
def test_propose_fixes_still_honours_max_findings(tmp_path, max_findings):
    router = ModelRouter(
        {"groq": _SlowClient("groq", delay=0.0, response="nope")},
        RouterConfig(max_retries=0, retry_backoff_seconds=0.0),
    )
    agent = FixAgent(router, Tracer("fixes", tmp_path / "logs"), primary_provider="groq")
    proposals = agent.propose_fixes([_finding(i) for i in range(10)], max_findings=max_findings)
    assert len(proposals) == max_findings
