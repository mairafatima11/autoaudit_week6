"""Security Agent batching and pipeline placement.

Security was the last agent still issuing one live model request per
finding, sequentially — and the worst one to leave that way, because
`semgrep --config=auto` returns hundreds of findings on a mid-sized repo
where the offline fallback scanner returns a handful. Worse, its model
calls ran inside the Supervisor's *parallel detection* phase, so Quality
and Documentation finished detecting in seconds and then sat blocked
behind it: the live pipeline view showed Security spinning for minutes
with everything queued behind it.
"""
from __future__ import annotations

import inspect
import re

import pytest

from autoaudit.agents.security_agent import DEFAULT_BATCH_SIZE, SecurityAgent, _PendingFinding
from autoaudit.agents.supervisor import Supervisor
from autoaudit.llm.base import LLMClient, ProviderUnavailable
from autoaudit.llm.router import ModelRouter, RouterConfig
from autoaudit.tracing import Tracer

_NUMBERED_MARKER_RE = re.compile(r"###ITEM \d+###")


class _BatchAwareClient(LLMClient):
    """Answers batched prompts using the ###ITEM n### protocol."""

    def __init__(self, provider: str = "groq"):
        self.provider = provider
        self.model = "test-model"
        self.mock = False
        self.calls = 0
        self.batch_sizes: list[int] = []

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls += 1
        # Count only numbered markers: the prompt's closing instruction
        # also contains a literal '###ITEM <n>###' example.
        n = len(_NUMBERED_MARKER_RE.findall(prompt))
        self.batch_sizes.append(max(1, n))
        if n > 1:
            return "\n".join(f"###ITEM {i + 1}###\nExplanation {i + 1}." for i in range(n))
        return "Single explanation."


class _UnparseableClient(_BatchAwareClient):
    """Answers, but ignores the batch protocol."""

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls += 1
        return "Here is one blob of prose covering everything, unnumbered."


def _pending(n: int) -> list[_PendingFinding]:
    return [
        _PendingFinding(
            prompt=f"Rule: r{i}\nFile: src/f{i}.py:{i}",
            file=f"src/f{i}.py", line=i, rule=f"rule-{i}", message=f"Issue {i}",
            severity="medium", evidence="code", source_tool="semgrep",
        )
        for i in range(n)
    ]


def _agent(tmp_path, client, batch_size=DEFAULT_BATCH_SIZE, vector_store=None):
    """`vector_store` is only needed by `detect()`; the drafting tests below
    exercise `draft()` directly and don't touch it."""
    router = ModelRouter({client.provider: client}, RouterConfig(max_retries=0, retry_backoff_seconds=0.0))
    return SecurityAgent(
        client, vector_store=vector_store, tracer=Tracer("sec", tmp_path / "logs"),
        router=router, provider=client.provider, batch_size=batch_size,
    )


@pytest.mark.parametrize("n_findings", [1, 8, 9, 50, 201])
def test_requests_scale_with_batches_not_findings(tmp_path, n_findings):
    client = _BatchAwareClient()
    findings = _agent(tmp_path, client).draft(_pending(n_findings))

    expected_calls = -(-n_findings // DEFAULT_BATCH_SIZE)  # ceil
    assert client.calls == expected_calls, (
        f"{n_findings} findings should cost {expected_calls} requests, not {client.calls}"
    )
    assert len(findings) == n_findings


def test_every_finding_keeps_its_own_explanation(tmp_path):
    """Batching must not misattribute text across findings."""
    client = _BatchAwareClient()
    findings = _agent(tmp_path, client).draft(_pending(5))

    assert [f.description for f in findings] == [f"Explanation {i + 1}." for i in range(5)]
    assert [f.file for f in findings] == [f"src/f{i}.py" for i in range(5)]


def test_finding_metadata_survives_batching(tmp_path):
    client = _BatchAwareClient()
    findings = _agent(tmp_path, client).draft(_pending(3))
    for i, f in enumerate(findings):
        assert f.line == i
        assert f.rule == f"rule-{i}"
        assert f.title == f"Issue {i}"
        assert f.severity == "medium"
        assert f.source_tool == "semgrep"
        assert f.category == "security"


def test_batch_size_is_configurable(tmp_path):
    client = _BatchAwareClient()
    _agent(tmp_path, client, batch_size=4).draft(_pending(12))
    assert client.calls == 3
    assert client.batch_sizes == [4, 4, 4]


def test_unparseable_batch_falls_back_per_item_without_losing_findings(tmp_path):
    """The provider is demonstrably up, so per-item retries are worth it."""
    client = _UnparseableClient()
    findings = _agent(tmp_path, client, batch_size=4).draft(_pending(4))

    assert len(findings) == 4
    assert all(f.description for f in findings)


def test_total_provider_outage_degrades_once_per_batch(tmp_path):
    """Retrying item-by-item against a provider that just refused would mean
    N more full backoff cycles."""
    down = _BatchAwareClient()
    down.complete = lambda *a, **k: (_ for _ in ()).throw(ProviderUnavailable("groq", "503"))
    agent = _agent(tmp_path, down, batch_size=8)

    findings = agent.draft(_pending(24))

    assert len(findings) == 24, "a provider outage must not lose security findings"
    assert agent.degraded_count == 24
    for i, f in enumerate(findings):
        # Detection is deterministic, so severity/rule/evidence still hold.
        assert f.rule == f"rule-{i}"
        assert f.severity == "medium"
        assert f"Issue {i}" in f.description


def test_detect_makes_no_model_calls(tmp_path, mock_repo_path):
    """`detect()` must stay deterministic so it can run in the parallel
    phase without blocking the other agents."""
    from autoaudit.agents.repository_agent import RepositoryAgent
    from autoaudit.memory.vector_store import VectorStore

    tracer = Tracer("sec_detect", tmp_path / "logs")
    store = VectorStore(tmp_path / "vs.db")
    repo_id, files, _tmp, root = RepositoryAgent(store, tracer).build_knowledge_base(mock_repo_path)

    client = _BatchAwareClient()
    agent = _agent(tmp_path, client, vector_store=store)
    try:
        pending = agent.detect(repo_id, str(root), files)
        assert pending, "should detect something in the mock repo"
        assert client.calls == 0, "detect() must not call a model"
        # Everything a Finding needs, minus the prose.
        for p in pending:
            assert p.file and p.rule and p.severity and p.prompt
    finally:
        store.close()


def test_supervisor_parallel_phase_has_no_model_calls_in_it():
    """Regression guard for the pipeline stall: Security's LLM work used to
    sit inside the parallel detection block."""
    src = inspect.getsource(Supervisor.run)
    parallel = src.split("parallel_agents.start")[1].split("parallel_agents.done")[0]

    assert "security_agent.detect" in parallel
    assert "security_agent.run" not in parallel, "model calls are back in the parallel phase"
    assert "quality_agent.detect" in parallel
    assert "doc_agent.detect" in parallel
    for drafting in ("security_agent.draft", "quality_agent.draft", "doc_agent.draft"):
        assert drafting not in parallel, f"{drafting} must run in the drafting phase"


def test_supervisor_drafts_security_in_the_drafting_phase():
    src = inspect.getsource(Supervisor.run)
    drafting = src.split("draft_agents.start")[1].split("draft_agents.done")[0]
    assert "security_agent.draft" in drafting


def test_run_still_works_as_detect_plus_draft(tmp_path, mock_repo_path):
    """Backwards compatibility for direct callers and existing tests."""
    from autoaudit.agents.repository_agent import RepositoryAgent
    from autoaudit.memory.vector_store import VectorStore

    tracer = Tracer("sec_run", tmp_path / "logs")
    store = VectorStore(tmp_path / "vs.db")
    repo_id, files, _tmp, root = RepositoryAgent(store, tracer).build_knowledge_base(mock_repo_path)

    client = _BatchAwareClient()
    agent = _agent(tmp_path, client, vector_store=store)
    try:
        findings = agent.run(repo_id, str(root), files)
        assert findings
        assert all(f.category == "security" for f in findings)
    finally:
        store.close()
