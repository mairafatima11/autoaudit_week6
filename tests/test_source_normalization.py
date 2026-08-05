"""Repository source handling.

A pasted URL with a single leading space produced:

    Repo path does not exist: https://github.com/pallets/flask

which reads as nonsense — the URL is obviously a URL. The space made
`startswith("https://")` False, so the URL was treated as a local
filesystem path; and because HTML collapses leading whitespace, the error
banner rendered a perfectly valid-looking URL with no hint of the cause.

Checking that also surfaced `repo_id_for`'s `.rstrip(".git")`, which strips
*characters* rather than a suffix.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoaudit.agents.repository_agent import repo_id_for
from autoaudit.api.app import create_app
from autoaudit.api.dependencies import get_audit_history, get_config, get_job_store, get_supervisor
from autoaudit.api.jobs import JobStore
from autoaudit.agents.supervisor import Supervisor
from autoaudit.config import Config
from autoaudit.memory.audit_history import AuditHistory
from autoaudit.tools.repo_reader import looks_like_url, normalize_source, resolve_repo

URL = "https://github.com/pallets/flask"


# --- normalization ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        f" {URL}",
        f"{URL} ",
        f"\t{URL}\n",
        f"  {URL}  ",
        f'"{URL}"',
        f"'{URL}'",
        f'  "{URL}"  ',
    ],
)
def test_padded_and_quoted_sources_normalize_to_the_bare_url(raw):
    assert normalize_source(raw) == URL


@pytest.mark.parametrize(
    "raw",
    [f" {URL}", f"{URL} ", f'"{URL}"', f"{URL}.git", "git@github.com:pallets/flask.git"],
)
def test_padded_sources_are_still_recognised_as_urls(raw):
    """The whole bug: a space flipped this to False and sent the URL down
    the local-filesystem path."""
    assert looks_like_url(raw) is True


@pytest.mark.parametrize("raw", ["/tmp/myrepo", "./relative", "C:/code/repo", ""])
def test_local_paths_are_not_treated_as_urls(raw):
    assert looks_like_url(raw) is False


def test_normalizing_an_empty_source_is_empty():
    assert normalize_source("   ") == ""
    assert normalize_source(None) == ""


# --- resolve_repo -----------------------------------------------------------


def test_padded_url_is_cloned_not_read_from_disk(tmp_path, monkeypatch):
    cloned = {}

    def fake_run(cmd, **kwargs):
        cloned["cmd"] = cmd
        Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    path, is_temp = resolve_repo(f"  {URL}  ", tmp_path)
    assert is_temp is True
    # The trimmed URL must be what git receives.
    assert URL in cloned["cmd"]
    assert f" {URL}" not in cloned["cmd"]


def test_missing_local_path_error_makes_whitespace_visible(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        resolve_repo(str(tmp_path / "nope"), tmp_path)
    message = str(exc.value)
    # Quoted, so a stray space or quote character is actually visible.
    assert "'" in message or '"' in message
    assert "https://" in message, "should hint at the URL form"


def test_empty_source_is_rejected_clearly(tmp_path):
    with pytest.raises(ValueError, match="No repository source"):
        resolve_repo("   ", tmp_path)


def test_a_file_is_not_accepted_as_a_repo(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x = 1")
    with pytest.raises(NotADirectoryError):
        resolve_repo(str(target), tmp_path)


def test_clone_failure_surfaces_gits_own_message(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd, b"", b"fatal: repository not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="repository not found"):
        resolve_repo(URL, tmp_path)


def test_missing_git_binary_is_explained(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="git is not installed"):
        resolve_repo(URL, tmp_path)


# --- repo identity ----------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        (URL, f" {URL}"),
        (URL, f"{URL} "),
        (URL, f"{URL}/"),
        (URL, f"{URL}.git"),
        (URL, f"{URL}.git/"),
        (URL, f'"{URL}"'),
    ],
)
def test_equivalent_sources_share_one_repo_id(a, b):
    """Otherwise one repository's audit history silently forks in two."""
    assert repo_id_for(a) == repo_id_for(b)


@pytest.mark.parametrize(
    "name", ["pytest", "config", "agit", "streamlit", "logging", "requests"]
)
def test_repo_names_ending_in_dot_g_i_or_t_are_not_mangled(name):
    """`.rstrip(".git")` strips characters, not a suffix: `pytest` became
    `pytes` and `config` became `conf`."""
    plain = f"https://github.com/owner/{name}"
    assert repo_id_for(plain) == repo_id_for(f"{plain}.git")
    # And distinct repos must not collide after truncation.
    assert repo_id_for(plain) != repo_id_for("https://github.com/owner/pytes")


def test_different_repos_still_get_different_ids():
    assert repo_id_for(URL) != repo_id_for("https://github.com/psf/requests")


# --- API boundary -----------------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    config = Config(
        mode="mock", groq_api_key=None, gemini_api_key=None,
        data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
    )
    supervisor = Supervisor(config)
    # One shared store: a fresh JobStore per request would lose every
    # in-flight job between the POST and the follow-up GET.
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


def test_api_normalizes_the_source_before_starting_a_run(client, mock_repo_path):
    resp = client.post("/api/audits", json={"source": f"  {mock_repo_path}  "})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    for _ in range(100):
        if client.get(f"/api/audits/{run_id}/status").json()["status"] in ("done", "error"):
            break
        time.sleep(0.1)

    status = client.get(f"/api/audits/{run_id}/status").json()
    assert status["status"] == "done", f"padded local path failed the run: {status.get('error')}"

    listed = next(r for r in client.get("/api/audits").json() if r["run_id"] == run_id)
    assert listed["repo_source"] == mock_repo_path, "padded source was persisted verbatim"


def test_padded_and_bare_sources_share_one_history(client, mock_repo_path):
    """The identity consequence: otherwise the second run looks like a
    brand-new repository and every finding is reported as new."""
    for source in (mock_repo_path, f"  {mock_repo_path}  "):
        run_id = client.post("/api/audits", json={"source": source}).json()["run_id"]
        for _ in range(100):
            if client.get(f"/api/audits/{run_id}/status").json()["status"] in ("done", "error"):
                break
            time.sleep(0.1)

    repos = client.get("/api/audits/repositories").json()["repositories"]
    assert len(repos) == 1, f"one repository forked into {len(repos)} histories"
    assert repos[0]["run_count"] == 2


def test_api_rejects_an_empty_source(client):
    assert client.post("/api/audits", json={"source": "   "}).status_code == 422
