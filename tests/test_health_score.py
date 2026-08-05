"""Regression tests for the Repository Health Score.

The score previously subtracted a flat penalty per finding from 100, which
made it a function of repository size: any repo past a couple hundred files
pinned quality/architecture/technical_debt at 0, so the number carried no
information and could not respond to the repo actually improving. It also
counted `fixed` findings (issues that no longer exist) against the repo and
hardcoded `test_coverage = 70` regardless of whether tests existed.
"""
from __future__ import annotations

from autoaudit.analysis.health_score import compute_health_score
from autoaudit.analysis.test_coverage import TestCoverageSignal, analyze_test_coverage
from autoaudit.schemas import (
    AuditReport,
    Category,
    DocSuggestion,
    FindingStatus,
    Severity,
    make_finding,
)
from autoaudit.tools.repo_reader import FileRecord


def _finding(i: int, category=Category.QUALITY, severity=Severity.LOW, rule="long-function"):
    return make_finding(
        file=f"src/module_{i}.py", line=i, category=category, rule=rule,
        title=f"Finding {i}", description="d", severity=severity,
        source_agent="quality", source_tool="heuristic",
    )


def _report(findings, files_scanned):
    return AuditReport(
        run_id="r", repo_id="repo", repo_source="src",
        findings=findings, files_scanned=files_scanned,
    )


def test_same_finding_count_scores_higher_in_a_larger_repo():
    """The core regression: scoring must be a density, not a raw count."""
    findings = [_finding(i) for i in range(50)]
    small = compute_health_score(_report(findings, files_scanned=25))
    large = compute_health_score(_report(findings, files_scanned=500))

    assert large.quality > small.quality
    assert large.architecture > small.architecture
    assert large.overall > small.overall


def test_large_repo_does_not_saturate_at_zero():
    """98 low-severity smells across 101 files used to score exactly 0 for
    quality, architecture and technical debt simultaneously."""
    findings = [_finding(i) for i in range(98)]
    score = compute_health_score(_report(findings, files_scanned=101))

    assert 0 < score.quality < 100
    assert 0 < score.architecture < 100
    assert 0 < score.technical_debt < 100


def test_score_responds_to_removing_findings():
    """A repo that fixes half its issues must score measurably better."""
    before = compute_health_score(_report([_finding(i) for i in range(40)], 100))
    after = compute_health_score(_report([_finding(i) for i in range(20)], 100))
    assert after.overall > before.overall
    assert after.quality > before.quality


def test_fixed_findings_do_not_count_against_the_score():
    open_findings = [_finding(i) for i in range(10)]
    resolved = [_finding(i) for i in range(100, 130)]
    for f in resolved:
        f.status = FindingStatus.FIXED.value

    only_open = compute_health_score(_report(open_findings, 50))
    with_resolved = compute_health_score(_report(open_findings + resolved, 50))

    assert with_resolved.model_dump() == only_open.model_dump()


def test_high_severity_costs_more_than_low():
    high = compute_health_score(
        _report([_finding(1, Category.SECURITY, Severity.HIGH, "dangerous-eval")], 50)
    )
    low = compute_health_score(
        _report([_finding(1, Category.SECURITY, Severity.LOW, "broad-except")], 50)
    )
    assert high.security < low.security


def test_clean_repo_scores_100_per_category():
    score = compute_health_score(_report([], 100))
    assert score.security == 100
    assert score.quality == 100
    assert score.architecture == 100
    assert score.documentation == 100


def test_documentation_reflects_share_of_affected_files():
    suggestions = [
        DocSuggestion(file=f"src/m{i}.py", kind="missing_docstring", suggestion="s")
        for i in range(10)
    ]
    sparse = compute_health_score(_report([], 100), doc_suggestions=suggestions)
    dense = compute_health_score(_report([], 12), doc_suggestions=suggestions)
    assert sparse.documentation > dense.documentation


def test_test_coverage_is_measured_not_hardcoded():
    """The old implementation returned 70 for every repository."""
    tested = compute_health_score(
        _report([], 10), test_signal=TestCoverageSignal(score=95, source_files=10, measured=True)
    )
    untested = compute_health_score(
        _report([], 10), test_signal=TestCoverageSignal(score=5, source_files=10, measured=True)
    )
    assert tested.test_coverage == 95
    assert untested.test_coverage == 5
    assert tested.overall > untested.overall


def test_unmeasurable_test_coverage_is_excluded_from_overall():
    """A docs-only repo shouldn't be marked down for tests we never measured."""
    signal = TestCoverageSignal(score=0, source_files=0, measured=False)
    score = compute_health_score(_report([], 5), test_signal=signal)
    assert score.test_coverage_measured is False
    # With the test category dropped, a clean repo is still a perfect score.
    assert score.overall == 100


# --- test-coverage analyzer -------------------------------------------------


def _py(path: str, content: str) -> FileRecord:
    return FileRecord(path=path, content=content, language="python")


def test_analyze_test_coverage_detects_a_tested_repo():
    files = [
        _py("src/auth.py", "def login():\n    return 1\n\ndef logout():\n    return 2\n"),
        _py("tests/test_auth.py", "from src import auth\n\ndef test_login():\n    assert auth.login()\n\ndef test_logout():\n    assert auth.logout()\n"),
    ]
    signal = analyze_test_coverage(files)
    assert signal.measured
    assert signal.test_files == 1
    assert signal.test_cases == 2
    assert signal.modules_with_tests == 1
    assert signal.score > 50


def test_analyze_test_coverage_detects_an_untested_repo():
    files = [
        _py("src/auth.py", "def login():\n    return 1\n"),
        _py("src/billing.py", "def charge():\n    return 2\n"),
    ]
    signal = analyze_test_coverage(files)
    assert signal.measured
    assert signal.test_files == 0
    assert signal.test_cases == 0
    assert signal.score == 0


def test_analyze_test_coverage_reports_not_measured_without_source():
    signal = analyze_test_coverage([FileRecord(path="config.yml", content="a: 1", language="yaml")])
    assert signal.measured is False


def test_tested_repo_outscores_untested_repo():
    tested = analyze_test_coverage([
        _py("src/a.py", "def f():\n    pass\n"),
        _py("tests/test_a.py", "from src import a\ndef test_f():\n    a.f()\n"),
    ])
    untested = analyze_test_coverage([_py("src/a.py", "def f():\n    pass\n")])
    assert tested.score > untested.score
