from __future__ import annotations

from pathlib import Path

from autoaudit.agents.report_agent import ReportAgent
from autoaudit.memory.audit_history import AuditHistory
from autoaudit.schemas import Category, Severity, make_finding


def _finding(rule="hardcoded-secret", severity=Severity.HIGH, line=1):
    return make_finding(
        file="a.py", line=line, category=Category.SECURITY, rule=rule,
        title=rule, description="d", severity=severity,
        source_agent="security", source_tool="fallback-scanner",
    )


def test_build_report_dedupes_identical_findings(tmp_path: Path):
    hist = AuditHistory(tmp_path / "hist.db")
    agent = ReportAgent(hist)
    f = _finding()
    f_dup = _finding()  # identical fingerprint

    report = agent.build_report(
        run_id="run1", repo_id="repoA", repo_source="src",
        findings=[f, f_dup], files_scanned=2, chunks_indexed=5,
    )
    assert len(report.findings) == 1
    hist.close()


def test_build_report_sorts_by_severity(tmp_path: Path):
    hist = AuditHistory(tmp_path / "hist.db")
    agent = ReportAgent(hist)
    low = _finding(rule="low-rule", severity=Severity.LOW, line=2)
    high = _finding(rule="high-rule", severity=Severity.HIGH, line=3)

    report = agent.build_report(
        run_id="run1", repo_id="repoA", repo_source="src",
        findings=[low, high], files_scanned=1, chunks_indexed=1,
    )
    assert report.findings[0].severity == "high"
    hist.close()


def test_build_report_second_run_shows_diff(tmp_path: Path):
    hist = AuditHistory(tmp_path / "hist.db")
    agent = ReportAgent(hist)
    f1 = _finding(rule="hardcoded-secret")

    report1 = agent.build_report(
        run_id="run1", repo_id="repoA", repo_source="src",
        findings=[f1], files_scanned=1, chunks_indexed=1,
    )
    assert report1.is_first_run is True

    f2 = _finding(rule="hardcoded-secret")  # same, recurring
    report2 = agent.build_report(
        run_id="run2", repo_id="repoA", repo_source="src",
        findings=[f2], files_scanned=1, chunks_indexed=1,
    )
    assert report2.is_first_run is False
    assert all(f.status == "recurring" for f in report2.findings)
    hist.close()


def test_render_markdown_contains_key_sections(tmp_path: Path):
    hist = AuditHistory(tmp_path / "hist.db")
    agent = ReportAgent(hist)
    report = agent.build_report(
        run_id="run1", repo_id="repoA", repo_source="src",
        findings=[_finding()], files_scanned=1, chunks_indexed=1,
    )
    md = ReportAgent.render_markdown(report)
    assert "# AutoAudit AI Report" in md
    assert "## Summary" in md
    assert "## Findings" in md
    assert "hardcoded-secret" in md
    hist.close()


def test_render_markdown_no_findings():
    from autoaudit.schemas import AuditReport
    report = AuditReport(run_id="r", repo_id="x", repo_source="src", findings=[])
    md = ReportAgent.render_markdown(report)
    assert "No findings" in md
