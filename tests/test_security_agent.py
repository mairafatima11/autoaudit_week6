from __future__ import annotations

from pathlib import Path

from autoaudit.agents.repository_agent import RepositoryAgent
from autoaudit.agents.security_agent import SecurityAgent
from autoaudit.llm.claude_client import ClaudeClient
from autoaudit.memory.vector_store import VectorStore
from autoaudit.tracing import Tracer


def _build_kb(tmp_path: Path, mock_repo_path: str):
    tracer = Tracer("test_run", tmp_path / "logs")
    store = VectorStore(tmp_path / "vs.db")
    agent = RepositoryAgent(store, tracer)
    repo_id, files, temp_dir, root = agent.build_knowledge_base(mock_repo_path)
    return store, tracer, repo_id, files, root


def test_security_agent_finds_planted_issues(tmp_path, mock_repo_path):
    store, tracer, repo_id, files, root = _build_kb(tmp_path, mock_repo_path)
    claude = ClaudeClient(mock=True)
    agent = SecurityAgent(claude, store, tracer)
    findings = agent.run(repo_id, str(root), files)
 
    rules = " ".join(f.rule.lower() for f in findings)
    titles = " ".join(f.title.lower() for f in findings)
    assert findings
    assert "secret" in rules or "secret" in titles
    assert "eval" in rules or "eval" in titles
    assert "sql" in rules or "sql" in titles
    assert "eval" in rules or "eval" in titles
    store.close()


def test_security_agent_findings_have_llm_generated_descriptions(tmp_path, mock_repo_path):
    store, tracer, repo_id, files, root = _build_kb(tmp_path, mock_repo_path)
    claude = ClaudeClient(mock=True)
    agent = SecurityAgent(claude, store, tracer)

    findings = agent.run(repo_id, str(root), files)
    assert all(f.description.startswith("[mock-claude]") for f in findings)
    store.close()


def test_security_agent_records_category_and_source(tmp_path, mock_repo_path):
    store, tracer, repo_id, files, root = _build_kb(tmp_path, mock_repo_path)
    claude = ClaudeClient(mock=True)
    agent = SecurityAgent(claude, store, tracer)

    findings = agent.run(repo_id, str(root), files)
    assert all(f.category == "security" for f in findings)
    assert all(f.source_agent == "security" for f in findings)
    store.close()
