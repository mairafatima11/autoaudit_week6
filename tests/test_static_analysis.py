from __future__ import annotations

from autoaudit.tools import static_analysis
from pathlib import Path

def _mock_repo_files(mock_repo_path):
    from autoaudit.tools import repo_reader
    records, _, _ = repo_reader.read_repo(mock_repo_path)
    return [(r.path, r.content) for r in records]


def test_fallback_scanner_when_semgrep_missing(monkeypatch, mock_repo_path):
    monkeypatch.setattr(static_analysis, "semgrep_available", lambda: False)
    files = _mock_repo_files(mock_repo_path)
    findings = static_analysis.scan(mock_repo_path, files)
    assert findings, "fallback scanner should find planted issues"
    assert all(f.source_tool == "fallback-scanner" for f in findings)


def test_fallback_scanner_catches_planted_issues(mock_repo_path):
    files = _mock_repo_files(mock_repo_path)
    findings = static_analysis.run_fallback_scanner(files)
    rules_found = {f.rule for f in findings}
    assert "hardcoded-secret" in rules_found
    assert "dangerous-eval" in rules_found
    assert "sql-string-concat" in rules_found
    assert "insecure-yaml-load" in rules_found
    assert "broad-except" in rules_found


def test_fallback_scanner_on_clean_code_finds_nothing():
    clean = [("clean.py", "def add(a, b):\n    return a + b\n")]
    findings = static_analysis.run_fallback_scanner(clean)
    assert findings == []


def test_semgrep_used_when_available(monkeypatch, mock_repo_path):
    monkeypatch.setattr(static_analysis, "semgrep_available", lambda: True)
    monkeypatch.setattr(static_analysis, "run_semgrep", lambda root: [
        static_analysis.RawFinding(
            file="src/app.py", line=3, rule="fake-rule", message="fake",
            severity="high", evidence="API_KEY = ...", source_tool="semgrep",
        )
    ])
    files = _mock_repo_files(mock_repo_path)
    findings = static_analysis.scan(mock_repo_path, files)
    assert any(f.source_tool == "semgrep" for f in findings)
    assert any(f.source_tool == "fallback-scanner" for f in findings)
    assert any(f.rule == "fake-rule" for f in findings)


def test_scan_degrades_gracefully_if_semgrep_errors(monkeypatch, mock_repo_path):
    monkeypatch.setattr(static_analysis, "semgrep_available", lambda: True)

    def boom(root):
        raise RuntimeError("semgrep exploded")

    monkeypatch.setattr(static_analysis, "run_semgrep", boom)
    files = _mock_repo_files(mock_repo_path)
    findings = static_analysis.scan(mock_repo_path, files)
    assert findings
    assert all(f.source_tool == "fallback-scanner" for f in findings)
