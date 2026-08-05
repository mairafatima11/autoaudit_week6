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


@pytest.fixture()
def client(tmp_path: Path):
    config = Config(mode="mock", groq_api_key=None, gemini_api_key=None, data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    supervisor = Supervisor(config)
    job_store = JobStore(supervisor, config.log_dir)

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    app.dependency_overrides[get_supervisor] = lambda: supervisor
    app.dependency_overrides[get_job_store] = lambda: job_store
    app.dependency_overrides[get_audit_history] = lambda: AuditHistory(config.data_dir / "audit_history.db")

    with TestClient(app) as c:
        yield c


def _run_audit_and_wait(client: TestClient, source: str = "tests/fixtures/mock_repo", timeout: float = 10.0) -> str:
    resp = client.post("/api/audits", json={"source": source})
    run_id = resp.json()["run_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/audits/{run_id}/status").json()
        if status["status"] in ("done", "error"):
            assert status["status"] == "done", status
            return run_id
        time.sleep(0.05)
    raise AssertionError("audit job did not complete in time")


def test_file_tree_endpoint(client: TestClient):
    run_id = _run_audit_and_wait(client)
    resp = client.get(f"/api/audits/{run_id}/files")
    assert resp.status_code == 200
    body = resp.json()
    assert body["file_count"] > 0
    assert body["tree"]["type"] == "dir"
    assert len(body["tree"]["children"]) > 0


def test_file_content_endpoint_includes_findings(client: TestClient):
    run_id = _run_audit_and_wait(client)
    tree = client.get(f"/api/audits/{run_id}/files").json()["tree"]

    def first_file_path(node):
        if node["type"] == "file":
            return node["path"]
        for c in node["children"]:
            found = first_file_path(c)
            if found:
                return found
        return None

    path = first_file_path(tree)
    assert path is not None

    resp = client.get(f"/api/audits/{run_id}/file", params={"path": path})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == path
    assert isinstance(body["content"], str) and len(body["content"]) > 0
    assert body["language"] in ("python", "text", "javascript", "typescript", "json", "yaml")
    assert isinstance(body["findings"], list)
    for finding in body["findings"]:
        assert "confidence" in finding
        assert 0.0 <= finding["confidence"] <= 1.0


def test_file_content_404_for_missing_path(client: TestClient):
    run_id = _run_audit_and_wait(client)
    resp = client.get(f"/api/audits/{run_id}/file", params={"path": "nonexistent/file.py"})
    assert resp.status_code == 404


def test_file_tree_404_for_unknown_run(client: TestClient):
    resp = client.get("/api/audits/does-not-exist/files")
    assert resp.status_code == 404
