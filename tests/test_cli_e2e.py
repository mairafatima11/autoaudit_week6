from __future__ import annotations

from pathlib import Path

import pytest

from autoaudit import cli


def _run_cli(monkeypatch, tmp_path: Path, args: list[str]) -> int:
    monkeypatch.setenv("AUTOAUDIT_MODE", "mock")
    monkeypatch.setenv("AUTOAUDIT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOAUDIT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)
    return cli.main(args)


def test_cli_run_produces_report_file(monkeypatch, tmp_path, mock_repo_path):
    rc = _run_cli(monkeypatch, tmp_path, ["run", mock_repo_path, "--output", "report.md"])
    assert rc == 0
    report_path = tmp_path / "report.md"
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "# AutoAudit AI Report" in text
    assert "Category:** security" in text
    assert "Rule:" in text


def test_second_run_shows_recurring(monkeypatch, tmp_path, mock_repo_path):
    _run_cli(monkeypatch, tmp_path, ["run", mock_repo_path, "--output", "r1.md"])
    _run_cli(monkeypatch, tmp_path, ["run", mock_repo_path, "--output", "r2.md"])

    r2_text = (tmp_path / "r2.md").read_text(encoding="utf-8")
    assert "Compared against previous run" in r2_text
    assert "🔁 Recurring" in r2_text
    assert "🆕 New: 0" in r2_text


def test_cli_no_command_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code != 0


def test_cli_unknown_repo_path_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOAUDIT_MODE", "mock")
    monkeypatch.setenv("AUTOAUDIT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTOAUDIT_LOG_DIR", str(tmp_path / "logs"))
    with pytest.raises(FileNotFoundError):
        cli.main(["run", str(tmp_path / "nope"), "--output", str(tmp_path / "r.md")])

