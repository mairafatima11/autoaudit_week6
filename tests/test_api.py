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
    config = Config(
        mode="mock",
        groq_api_key=None,
        gemini_api_key=None,
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
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
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/audits/{run_id}/status").json()
        if status["status"] in ("done", "error"):
            assert status["status"] == "done", status
            return run_id
        time.sleep(0.05)
    raise AssertionError("audit job did not complete in time")


def test_health_check(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_start_and_poll_audit(client: TestClient):
    run_id = _run_audit_and_wait(client)
    assert run_id


def test_audit_status_progress_reaches_100_percent(client: TestClient):
    run_id = _run_audit_and_wait(client)
    status = client.get(f"/api/audits/{run_id}/status").json()
    assert status["percent"] == 100
    assert all(s["status"] == "completed" for s in status["stages"])


def test_audit_events_are_recorded(client: TestClient):
    run_id = _run_audit_and_wait(client)
    events = client.get(f"/api/audits/{run_id}/events").json()["events"]
    actors = {e["actor"] for e in events}
    assert "supervisor" in actors
    assert "security_agent" in actors
    assert "quality_agent" in actors


def test_get_full_report_includes_health_score(client: TestClient):
    run_id = _run_audit_and_wait(client)
    resp = client.get(f"/api/audits/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report"]["run_id"] == run_id
    assert len(body["report"]["findings"]) > 0
    assert 0 <= body["health_score"]["overall"] <= 100


def test_export_markdown_and_html_and_json(client: TestClient):
    run_id = _run_audit_and_wait(client)
    md = client.get(f"/api/audits/{run_id}/report.md")
    assert md.status_code == 200
    assert "# AutoAudit AI Report" in md.text

    html = client.get(f"/api/audits/{run_id}/report.html")
    assert html.status_code == 200
    assert "<html>" in html.text

    js = client.get(f"/api/audits/{run_id}/report.json")
    assert js.status_code == 200
    assert js.json()["report"]["run_id"] == run_id


def test_export_pdf(client: TestClient):
    run_id = _run_audit_and_wait(client)
    resp = client.get(f"/api/audits/{run_id}/report.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 1000


def test_propose_fixes_endpoint(client: TestClient):
    run_id = _run_audit_and_wait(client)
    resp = client.post(f"/api/audits/{run_id}/fixes", json={"max_findings": 2})
    assert resp.status_code == 200
    fixes = resp.json()
    assert len(fixes) <= 2
    for fx in fixes:
        assert "patch" in fx and "pr_title" in fx


def test_list_audits_shows_completed_run(client: TestClient):
    run_id = _run_audit_and_wait(client)
    resp = client.get("/api/audits")
    assert resp.status_code == 200
    run_ids = {r["run_id"] for r in resp.json()}
    assert run_id in run_ids


def test_compare_runs_endpoint(client: TestClient):
    run_a = _run_audit_and_wait(client)
    run_b = _run_audit_and_wait(client)
    resp = client.get("/api/audits/compare", params={"run_a": run_a, "run_b": run_b})
    assert resp.status_code == 200
    body = resp.json()
    assert "health_score_delta" in body
    assert "trend_summary" in body


def test_model_comparison_endpoint(client: TestClient):
    resp = client.post("/api/models/compare", json={"prompt": "explain eval() risk"})
    assert resp.status_code == 200
    body = resp.json()
    providers = {r["provider"] for r in body["results"]}
    assert providers == {"groq", "gemini"}


def test_available_models_endpoint(client: TestClient):
    resp = client.get("/api/models/available")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()["providers"]}
    assert ids == {"groq", "gemini"}


def test_status_404_for_unknown_run(client: TestClient):
    resp = client.get("/api/audits/does-not-exist/status")
    assert resp.status_code == 404


def test_get_audit_404_for_unknown_run(client: TestClient):
    resp = client.get("/api/audits/does-not-exist")
    assert resp.status_code == 404
