from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoaudit.agents.supervisor import Supervisor
from autoaudit.api.app import create_app
from autoaudit.api.dependencies import get_config, get_job_store, get_supervisor
from autoaudit.api.jobs import JobStore
from autoaudit.config import Config


def _make_client(api_key: str | None, tmp_path: Path) -> TestClient:
    config = Config(
        mode="mock", groq_api_key=None, gemini_api_key=None,
        data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
        api_key=api_key,
    )
    supervisor = Supervisor(config)
    job_store = JobStore(supervisor, config.log_dir)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    app.dependency_overrides[get_supervisor] = lambda: supervisor
    app.dependency_overrides[get_job_store] = lambda: job_store
    return TestClient(app)


def test_auth_disabled_by_default(tmp_path: Path):
    client = _make_client(api_key=None, tmp_path=tmp_path)
    resp = client.get("/api/audits")
    assert resp.status_code == 200


def test_health_check_always_reachable_even_with_key_set(tmp_path: Path):
    client = _make_client(api_key="secret123", tmp_path=tmp_path)
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_protected_route_rejects_missing_key(tmp_path: Path):
    client = _make_client(api_key="secret123", tmp_path=tmp_path)
    resp = client.get("/api/audits")
    assert resp.status_code == 401
    assert "Authorization" in resp.json()["detail"]


def test_protected_route_rejects_wrong_key(tmp_path: Path):
    client = _make_client(api_key="secret123", tmp_path=tmp_path)
    resp = client.get("/api/audits", headers={"Authorization": "Bearer wrong-key"})
    assert resp.status_code == 401


def test_protected_route_accepts_correct_key(tmp_path: Path):
    client = _make_client(api_key="secret123", tmp_path=tmp_path)
    resp = client.get("/api/audits", headers={"Authorization": "Bearer secret123"})
    assert resp.status_code == 200


def test_docs_reachable_without_key(tmp_path: Path):
    client = _make_client(api_key="secret123", tmp_path=tmp_path)
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_malformed_authorization_header_rejected(tmp_path: Path):
    client = _make_client(api_key="secret123", tmp_path=tmp_path)
    resp = client.get("/api/audits", headers={"Authorization": "secret123"})  # missing "Bearer " prefix
    assert resp.status_code == 401


def test_cors_headers_present_on_401_response(tmp_path: Path):
    """Regression check: the auth middleware must not swallow CORS headers
    on its own error responses, or the frontend would see an opaque CORS
    failure instead of a readable 401 when a key is required but missing."""
    client = _make_client(api_key="secret123", tmp_path=tmp_path)
    resp = client.get("/api/audits", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 401
    assert resp.headers.get("access-control-allow-origin") is not None
