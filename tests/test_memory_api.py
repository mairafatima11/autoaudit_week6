"""Tests for the Memory page's backing data.

These cover behaviour the page previously could not have rendered correctly:
per-repository scoping (trends were charted across every repo in the DB at
once), knowledge-base statistics (no endpoint existed), recurring findings
(never computed), and persisted per-run counts (historical runs reported
0 chunks indexed and a files count guessed from finding paths).
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoaudit.agents.supervisor import Supervisor
from autoaudit.api.app import create_app
from autoaudit.api.dependencies import get_audit_history, get_config, get_job_store, get_supervisor
from autoaudit.api.jobs import JobStore
from autoaudit.config import Config
from autoaudit.memory.audit_history import AuditHistory
from autoaudit.schemas import Category, RepoHealthScore, Severity, make_finding


@pytest.fixture()
def history(tmp_path):
    h = AuditHistory(tmp_path / "history.db")
    yield h
    h.close()


@pytest.fixture()
def client(tmp_path: Path):
    config = Config(
        mode="mock", groq_api_key=None, gemini_api_key=None,
        data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
    )
    supervisor = Supervisor(config)
    job_store = JobStore(supervisor, config.log_dir, config.data_dir / "audit_history.db")

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    app.dependency_overrides[get_supervisor] = lambda: supervisor
    app.dependency_overrides[get_job_store] = lambda: job_store
    app.dependency_overrides[get_audit_history] = lambda: AuditHistory(
        config.data_dir / "audit_history.db"
    )
    with TestClient(app) as c:
        yield c


def _run_audit(client: TestClient, source: str = "tests/fixtures/mock_repo") -> str:
    run_id = client.post("/api/audits", json={"source": source}).json()["run_id"]
    for _ in range(100):
        if client.get(f"/api/audits/{run_id}/status").json()["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    return run_id


def _finding(i, rule="long-function", severity=Severity.LOW):
    return make_finding(
        file=f"src/m{i}.py", line=i, category=Category.QUALITY, rule=rule,
        title=f"F{i}", description="d", severity=severity,
        source_agent="quality", source_tool="heuristic",
    )


def test_list_runs_scopes_to_a_repository(history):
    history.save_run("r1", "repo-a", "a", [_finding(1)])
    history.save_run("r2", "repo-b", "b", [_finding(2)])

    assert {r["run_id"] for r in history.list_runs("repo-a")} == {"r1"}
    assert {r["run_id"] for r in history.list_runs()} == {"r1", "r2"}


def test_list_runs_carries_counts_and_health_score(history):
    history.save_run(
        "r1", "repo-a", "a",
        [_finding(1, severity=Severity.HIGH), _finding(2), _finding(3)],
        files_scanned=120, chunks_indexed=980,
    )
    history.save_health_score("r1", RepoHealthScore(
        overall=71, security=80, quality=60, documentation=70,
        architecture=65, test_coverage=55, technical_debt=62,
    ))

    row = history.list_runs("repo-a")[0]
    assert row["files_scanned"] == 120
    assert row["chunks_indexed"] == 980
    assert row["finding_count"] == 3
    assert row["severity_counts"] == {"high": 1, "medium": 0, "low": 2, "info": 0}
    assert row["health_score"]["overall"] == 71


def test_list_runs_health_score_is_none_when_never_persisted(history):
    history.save_run("r1", "repo-a", "a", [])
    assert history.list_runs("repo-a")[0]["health_score"] is None


def test_repositories_groups_runs(history):
    history.save_run("r1", "repo-a", "https://github.com/x/a", [])
    time.sleep(0.01)
    history.save_run("r2", "repo-a", "https://github.com/x/a", [])
    history.save_run("r3", "repo-b", "https://github.com/x/b", [])

    repos = {r["repo_id"]: r for r in history.repositories()}
    assert repos["repo-a"]["run_count"] == 2
    assert repos["repo-b"]["run_count"] == 1
    assert repos["repo-a"]["last_run_ts"] >= repos["repo-a"]["first_run_ts"]


def test_recurring_findings_counts_distinct_runs(history):
    persistent = _finding(1)
    history.save_run("r1", "repo-a", "a", [persistent, _finding(2)])
    history.save_run("r2", "repo-a", "a", [persistent, _finding(3)])
    history.save_run("r3", "repo-a", "a", [persistent])

    recurring = history.recurring_findings("repo-a")
    assert len(recurring) == 1
    assert recurring[0]["fingerprint"] == persistent.fingerprint
    assert recurring[0]["run_count"] == 3


def test_recurring_findings_catches_reintroduced_issues(history):
    """Fixed-then-reintroduced still counts as recurring — a single pairwise
    run diff would miss this."""
    flaky = _finding(9)
    history.save_run("r1", "repo-a", "a", [flaky])
    history.save_run("r2", "repo-a", "a", [])
    history.save_run("r3", "repo-a", "a", [flaky])

    assert [f["fingerprint"] for f in history.recurring_findings("repo-a")] == [flaky.fingerprint]


def test_recurring_findings_are_scoped_per_repo(history):
    shared = _finding(1)
    history.save_run("r1", "repo-a", "a", [shared])
    history.save_run("r2", "repo-b", "b", [shared])
    assert history.recurring_findings("repo-a") == []


# --- HTTP surface ----------------------------------------------------------


def test_run_list_endpoint_carries_everything_the_memory_page_charts(client):
    run_id = _run_audit(client)
    rows = client.get("/api/audits").json()
    row = next(r for r in rows if r["run_id"] == run_id)

    assert row["health_score"] is not None, "health score must be persisted on completion"
    assert row["files_scanned"] and row["files_scanned"] > 0
    assert row["chunks_indexed"] and row["chunks_indexed"] > 0
    assert set(row["severity_counts"]) == {"high", "medium", "low", "info"}


def test_run_list_can_be_scoped_to_one_repository(client, tmp_path):
    other = tmp_path / "other_repo"
    other.mkdir()
    (other / "only.py").write_text("def f():\n    return 1\n")

    _run_audit(client)
    _run_audit(client, str(other))

    repos = client.get("/api/audits/repositories").json()["repositories"]
    assert len(repos) == 2

    for repo in repos:
        scoped = client.get("/api/audits", params={"repo_id": repo["repo_id"]}).json()
        assert scoped, repo
        assert {r["repo_id"] for r in scoped} == {repo["repo_id"]}


def test_recurring_endpoint_reports_issues_seen_in_multiple_runs(client):
    _run_audit(client)
    _run_audit(client)

    repo_id = client.get("/api/audits/repositories").json()["repositories"][0]["repo_id"]
    findings = client.get("/api/audits/recurring", params={"repo_id": repo_id}).json()["findings"]
    assert findings
    assert all(f["run_count"] >= 2 for f in findings)


def test_knowledge_base_endpoint_reports_real_chunk_counts(client):
    _run_audit(client)
    repo_id = client.get("/api/audits/repositories").json()["repositories"][0]["repo_id"]

    kb = client.get("/api/memory/knowledge-base", params={"repo_id": repo_id}).json()
    assert kb["total_chunks"] > 0
    assert kb["embedding_dim"] > 0
    assert kb["top_files"]
    assert all(f["chunks"] > 0 for f in kb["top_files"])


def test_knowledge_base_endpoint_summarises_all_repos_without_a_filter(client):
    _run_audit(client)
    kb = client.get("/api/memory/knowledge-base").json()
    assert kb["indexed_repositories"] >= 1
    assert kb["total_chunks"] > 0


def test_knowledge_base_search_returns_ranked_chunks(client):
    _run_audit(client)
    repo_id = client.get("/api/audits/repositories").json()["repositories"][0]["repo_id"]

    resp = client.get("/api/memory/search", params={"repo_id": repo_id, "q": "add numbers"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True), "results must be ranked"


def test_knowledge_base_search_rejects_an_empty_query(client):
    assert client.get("/api/memory/search", params={"repo_id": "x", "q": "   "}).status_code == 422


def test_health_score_is_consistent_between_detail_and_comparison(client):
    """The detail view and the comparison view must agree — they previously
    resolved the score by different routes and could disagree for the same
    run."""
    a = _run_audit(client)
    b = _run_audit(client)

    detail_a = client.get(f"/api/audits/{a}").json()["health_score"]
    detail_b = client.get(f"/api/audits/{b}").json()["health_score"]
    cmp = client.get("/api/audits/compare", params={"run_a": a, "run_b": b}).json()

    assert cmp["health_score_a"] == detail_a
    assert cmp["health_score_b"] == detail_b
    assert cmp["health_score_delta"] == detail_b["overall"] - detail_a["overall"]


def test_migration_adds_new_columns_to_an_old_db(tmp_path):
    """A DB created before files_scanned/chunks_indexed existed must open."""
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """CREATE TABLE runs (run_id TEXT PRIMARY KEY, repo_id TEXT NOT NULL,
                              repo_source TEXT NOT NULL, ts REAL NOT NULL);
           CREATE TABLE findings (run_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                              file TEXT NOT NULL, line INTEGER NOT NULL,
                              category TEXT NOT NULL, rule TEXT NOT NULL,
                              title TEXT NOT NULL, description TEXT NOT NULL,
                              severity TEXT NOT NULL, source_agent TEXT NOT NULL,
                              source_tool TEXT NOT NULL,
                              PRIMARY KEY (run_id, fingerprint));"""
    )
    conn.execute("INSERT INTO runs VALUES ('old1', 'repo-a', 'a', 1.0)")
    conn.commit()
    conn.close()

    h = AuditHistory(path)
    try:
        row = h.list_runs("repo-a")[0]
        assert row["run_id"] == "old1"
        assert row["files_scanned"] is None
        assert row["chunks_indexed"] is None
        assert row["health_score"] is None
    finally:
        h.close()
