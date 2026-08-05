from __future__ import annotations

from unittest.mock import patch

import pytest
import requests
from fastapi.testclient import TestClient

from autoaudit.agents.supervisor import Supervisor
from autoaudit.api.app import create_app
from autoaudit.api.dependencies import get_config, get_supervisor
from autoaudit.config import Config
from autoaudit.tools.github_client import fetch_repo_metadata, parse_github_source


def test_parse_github_source_variants():
    assert parse_github_source("https://github.com/psf/requests") == ("psf", "requests")
    assert parse_github_source("https://github.com/psf/requests.git") == ("psf", "requests")
    assert parse_github_source("git@github.com:psf/requests.git") == ("psf", "requests")
    assert parse_github_source("/local/path/to/repo") is None
    assert parse_github_source("tests/fixtures/mock_repo") is None


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_repo_metadata_success():
    repo_payload = {
        "owner": {"login": "psf"},
        "name": "requests",
        "full_name": "psf/requests",
        "description": "A simple HTTP library",
        "default_branch": "main",
        "language": "Python",
        "size": 4200,
        "stargazers_count": 52000,
        "forks_count": 9300,
        "open_issues_count": 120,
        "watchers_count": 52000,
        "license": {"spdx_id": "Apache-2.0"},
        "topics": ["http", "python"],
        "fork": False,
        "archived": False,
        "created_at": "2011-02-13T18:38:17Z",
        "pushed_at": "2024-01-01T00:00:00Z",
        "html_url": "https://github.com/psf/requests",
    }
    commit_payload = [{"author": {"login": "octocat"}, "commit": {"author": {"date": "2024-01-01T00:00:00Z"}, "message": "Fix bug\n\nmore detail"}}]

    def fake_get(url, headers=None, timeout=None, params=None):
        if url.endswith("/commits"):
            return _FakeResponse(200, commit_payload)
        return _FakeResponse(200, repo_payload)

    with patch("autoaudit.tools.github_client.requests.get", side_effect=fake_get):
        meta = fetch_repo_metadata("https://github.com/psf/requests")

    assert meta["stars"] == 52000
    assert meta["forks"] == 9300
    assert meta["default_branch"] == "main"
    assert meta["last_commit_author"] == "octocat"
    assert meta["last_commit_message"] == "Fix bug"


def test_fetch_repo_metadata_non_github_source_returns_none():
    assert fetch_repo_metadata("tests/fixtures/mock_repo") is None


def test_fetch_repo_metadata_handles_error_status():
    with patch("autoaudit.tools.github_client.requests.get", return_value=_FakeResponse(404, {})):
        meta = fetch_repo_metadata("https://github.com/nonexistent/repo")
    assert "error" in meta


def test_fetch_repo_metadata_handles_network_failure():
    with patch("autoaudit.tools.github_client.requests.get", side_effect=requests.RequestException("boom")):
        meta = fetch_repo_metadata("https://github.com/psf/requests")
    assert "error" in meta


@pytest.fixture()
def client(tmp_path):
    config = Config(mode="mock", groq_api_key=None, gemini_api_key=None, data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    supervisor = Supervisor(config)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    app.dependency_overrides[get_supervisor] = lambda: supervisor
    with TestClient(app) as c:
        yield c


def test_repository_metadata_endpoint_non_github(client: TestClient):
    resp = client.get("/api/repository/metadata", params={"source": "tests/fixtures/mock_repo"})
    assert resp.status_code == 200
    assert resp.json()["available"] is False


def test_repository_metadata_endpoint_github(client: TestClient):
    def fake_get(url, headers=None, timeout=None, params=None):
        if url.endswith("/commits"):
            return _FakeResponse(200, [])
        return _FakeResponse(200, {
            "owner": {"login": "psf"}, "name": "requests", "full_name": "psf/requests",
            "stargazers_count": 100, "forks_count": 5, "default_branch": "main",
        })

    with patch("autoaudit.tools.github_client.requests.get", side_effect=fake_get):
        resp = client.get("/api/repository/metadata", params={"source": "https://github.com/psf/requests"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["stars"] == 100
