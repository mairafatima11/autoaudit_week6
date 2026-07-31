from __future__ import annotations

from pathlib import Path

from autoaudit.memory.audit_history import AuditHistory
from autoaudit.schemas import Category, Severity, make_finding


def _finding(file="a.py", line=1, rule="hardcoded-secret"):
    return make_finding(
        file=file, line=line, category=Category.SECURITY, rule=rule,
        title="t", description="d", severity=Severity.HIGH,
        source_agent="security", source_tool="fallback-scanner",
    )


def test_first_run_marks_everything_new(tmp_path: Path):
    hist = AuditHistory(tmp_path / "hist.db")
    findings = [_finding()]
    tagged, is_first = hist.diff_against_last("repoA", "run1", findings)
    assert is_first is True
    assert all(f.status == "new" for f in tagged)
    hist.save_run("run1", "repoA", "src", findings)
    hist.close()


def test_second_run_marks_recurring(tmp_path: Path):
    hist = AuditHistory(tmp_path / "hist.db")
    f1 = [_finding()]
    hist.diff_against_last("repoA", "run1", f1)
    hist.save_run("run1", "repoA", "src", f1)

    f2 = [_finding()]  
    tagged, is_first = hist.diff_against_last("repoA", "run2", f2)
    assert is_first is False
    assert all(f.status == "recurring" for f in tagged if f.source_agent != "audit-history")
    hist.close()


def test_diff_marks_fixed_findings(tmp_path: Path):
    hist = AuditHistory(tmp_path / "hist.db")
    f1 = [_finding(rule="hardcoded-secret"), _finding(rule="dangerous-eval", line=5)]
    hist.diff_against_last("repoA", "run1", f1)
    hist.save_run("run1", "repoA", "src", f1)

    f2 = [_finding(rule="hardcoded-secret")]  
    tagged, _ = hist.diff_against_last("repoA", "run2", f2)
    fixed = [f for f in tagged if f.status == "fixed"]
    assert len(fixed) == 1
    assert fixed[0].rule == "dangerous-eval"
    hist.close()


def test_new_finding_on_second_run_marked_new(tmp_path: Path):
    hist = AuditHistory(tmp_path / "hist.db")
    f1 = [_finding(rule="hardcoded-secret")]
    hist.diff_against_last("repoA", "run1", f1)
    hist.save_run("run1", "repoA", "src", f1)

    f2 = [_finding(rule="hardcoded-secret"), _finding(rule="dangerous-eval", line=9)]
    tagged, _ = hist.diff_against_last("repoA", "run2", f2)
    new_ones = [f for f in tagged if f.status == "new"]
    assert len(new_ones) == 1
    assert new_ones[0].rule == "dangerous-eval"
    hist.close()


def test_different_repos_do_not_interfere(tmp_path: Path):
    hist = AuditHistory(tmp_path / "hist.db")
    fa = [_finding(rule="hardcoded-secret")]
    hist.diff_against_last("repoA", "run1", fa)
    hist.save_run("run1", "repoA", "src", fa)

    fb = [_finding(rule="dangerous-eval")]
    tagged, is_first = hist.diff_against_last("repoB", "run2", fb)
    assert is_first is True 
    hist.close()
