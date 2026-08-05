from __future__ import annotations

from pathlib import Path

from autoaudit.agents.quality_agent import QualityAgent
from autoaudit.agents.repository_agent import RepositoryAgent
from autoaudit.llm.gemini_client import GeminiClient
from autoaudit.memory.vector_store import VectorStore
from autoaudit.tracing import Tracer


def _build_kb(tmp_path: Path, mock_repo_path: str):
    tracer = Tracer("test_run", tmp_path / "logs")
    store = VectorStore(tmp_path / "vs.db")
    agent = RepositoryAgent(store, tracer)
    repo_id, files, temp_dir, root = agent.build_knowledge_base(mock_repo_path)
    return store, tracer, repo_id, files


def test_quality_agent_flags_long_function(tmp_path, mock_repo_path):
    store, tracer, repo_id, files = _build_kb(tmp_path, mock_repo_path)
    gemini = GeminiClient(mock=True)
    agent = QualityAgent(gemini, store, tracer, long_function_threshold=40)

    findings = agent.run(repo_id, files)
    long_fn_findings = [f for f in findings if f.rule == "long-function"]
    assert long_fn_findings
    assert any("long_running_task" in f.evidence or "compute_totals" in f.evidence for f in long_fn_findings)
    store.close()


def test_quality_agent_does_not_duplicate_documentation_findings(tmp_path, mock_repo_path):
    """Missing docstrings are DocumentationAgent's responsibility only.

    They used to be detected here as well, so every gap was reported twice
    under two different categories and the Quality score was dragged down by
    a documentation signal. This test locks in the single-owner split — see
    the QualityAgent module docstring.
    """
    store, tracer, repo_id, files = _build_kb(tmp_path, mock_repo_path)
    gemini = GeminiClient(mock=True)
    agent = QualityAgent(gemini, store, tracer)

    findings = agent.run(repo_id, files)
    assert [f for f in findings if f.rule == "missing-docstring"] == []
    assert all(f.category == "quality" for f in findings)
    store.close()


def test_quality_agent_flags_duplicate_code(tmp_path, mock_repo_path):
    store, tracer, repo_id, files = _build_kb(tmp_path, mock_repo_path)
    gemini = GeminiClient(mock=True)
    agent = QualityAgent(gemini, store, tracer)

    findings = agent.run(repo_id, files)
    dup_findings = [f for f in findings if f.rule == "duplicate-code"]
    assert dup_findings, "long_running_task and compute_totals are near-identical and should be flagged"
    store.close()


def test_quality_agent_higher_threshold_finds_fewer_long_functions(tmp_path, mock_repo_path):
    store, tracer, repo_id, files = _build_kb(tmp_path, mock_repo_path)
    gemini = GeminiClient(mock=True)
    agent_strict = QualityAgent(gemini, store, tracer, long_function_threshold=1000)

    findings = agent_strict.run(repo_id, files)
    assert not [f for f in findings if f.rule == "long-function"]
    store.close()
