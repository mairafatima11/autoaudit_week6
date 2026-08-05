"""Repository Health Score (0-100 composite + category breakdown).

Scoring is **density-based**: every category converts its findings into a
weighted penalty *per scanned file*, then maps that density onto 0-100 with
a smooth curve. The previous implementation subtracted a flat penalty per
finding from a starting score of 100, which made the score a function of
repository size rather than repository quality:

    flask   (~250 files,  54 low-severity quality findings) -> quality 0
    click   (~101 files,  98 low-severity quality findings) -> quality 0
    architecture / technical_debt on both                   -> 0

Any repository past a couple of hundred files saturated at 0 in three of
six categories, so the composite score carried almost no information and
"improving the repo" could not move the number. Densities fix that: the
same 54 findings score very differently in a 25-file repo than in a
250-file one, and the curve below is asymptotic, so a score approaches 0
without ever slamming into it.

Findings whose status is `fixed` are excluded throughout. Those are
history entries the audit-history diff reconstructs for issues that are no
longer in the code (see `memory/audit_history.diff_against_last`); counting
them meant a repository was still penalised for problems it had already
resolved, and the score moved the wrong way after a genuine fix.
"""
from __future__ import annotations

from ..schemas import AuditReport, DocSuggestion, RepoHealthScore, plain
from .test_coverage import TestCoverageSignal

# Weighted "damage" per finding, by severity. Relative weights matter more
# than absolute values — the D_* half-life constants below are what set the
# actual scale.
_SEVERITY_WEIGHT = {"high": 10.0, "medium": 4.0, "low": 1.0, "info": 0.25}

# Penalty density at which a category scores 50/100. Chosen so that:
#   security      0.5  ~= one high-severity finding per 20 files
#   quality       1.5  ~= 1.5 low-severity smells per file
#   architecture  0.8  ~= one long function per file and change
#   technical debt 1.2 ~= combined smell + doc-gap pressure
_D_SECURITY = 0.5
_D_QUALITY = 1.5
_D_ARCHITECTURE = 0.8
_D_TECH_DEBT = 1.2

# Composite weights (must sum to 1.0).
_COMPOSITE_WEIGHTS = {
    "security": 0.30,
    "quality": 0.20,
    "documentation": 0.15,
    "architecture": 0.15,
    "test_coverage": 0.10,
    "technical_debt": 0.10,
}


def _score_from_density(density: float, half_life: float) -> int:
    """Map a non-negative penalty density onto 0-100.

    Hyperbolic decay: `density == half_life` scores exactly 50, and the
    curve approaches 0 asymptotically instead of clamping there. This is
    what keeps a large repository's score responsive — with the old linear
    subtraction, once enough findings accumulated every further change was
    invisible because the score was already pinned at the floor.
    """
    if density <= 0:
        return 100
    return max(0, min(100, round(100 / (1 + density / half_life))))


def _active(findings):
    """Findings that still exist in the code (see module docstring)."""
    return [f for f in findings if plain(f.status) != "fixed"]


def _penalty(findings, categories: set[str]) -> float:
    total = 0.0
    for f in findings:
        if plain(f.category) not in categories:
            continue
        total += _SEVERITY_WEIGHT.get(plain(f.severity), 1.0)
    return total


def compute_health_score(
    report: AuditReport,
    doc_suggestions: list[DocSuggestion] | None = None,
    files_scanned: int | None = None,
    test_signal: TestCoverageSignal | None = None,
) -> RepoHealthScore:
    findings = _active(report.findings)

    files = files_scanned if files_scanned is not None else report.files_scanned
    files = max(int(files or 0), 1)

    security = _score_from_density(_penalty(findings, {"security"}) / files, _D_SECURITY)
    quality = _score_from_density(_penalty(findings, {"quality"}) / files, _D_QUALITY)

    # Documentation: share of files carrying at least one documentation gap.
    # Counting *distinct affected files* rather than raw gap count means one
    # messy module and gaps spread thinly across the repo are scored by how
    # much of the codebase is actually affected, not by depth in a single file.
    suggestions = doc_suggestions if doc_suggestions is not None else report.doc_suggestions
    affected_files = len({s.file for s in (suggestions or [])})
    documentation = max(0, min(100, round(100 - min(1.0, affected_files / files) * 100)))

    # Architecture / technical-debt proxies. Long functions and duplicated
    # blocks are the strongest structural signals available without a
    # dedicated architecture agent, so they're weighted rather than counted.
    long_fn = sum(1 for f in findings if f.rule == "long-function")
    dup = sum(1 for f in findings if f.rule == "duplicate-code")
    architecture = _score_from_density((long_fn * 1.0 + dup * 1.5) / files, _D_ARCHITECTURE)

    # Technical debt blends structural smells with documentation debt — an
    # undocumented codebase is harder to change even when its structure is fine.
    debt_density = (long_fn * 1.0 + dup * 1.5 + affected_files * 0.5) / files
    technical_debt = _score_from_density(debt_density, _D_TECH_DEBT)

    # Real, observed test signal (see analysis/test_coverage.py). When a repo
    # has no source to test, the category is dropped from the composite and
    # the remaining weights are renormalised, rather than scoring it 0 and
    # dragging the overall number down for something we didn't measure.
    if test_signal is not None and test_signal.measured:
        test_coverage = test_signal.score
        include_tests = True
    elif test_signal is not None:
        test_coverage = 0
        include_tests = False
    else:
        test_coverage = 0
        include_tests = False

    parts = {
        "security": security,
        "quality": quality,
        "documentation": documentation,
        "architecture": architecture,
        "test_coverage": test_coverage,
        "technical_debt": technical_debt,
    }
    weights = dict(_COMPOSITE_WEIGHTS)
    if not include_tests:
        weights.pop("test_coverage")
    total_weight = sum(weights.values())
    overall = round(sum(parts[k] * w for k, w in weights.items()) / total_weight)

    return RepoHealthScore(
        overall=max(0, min(100, overall)),
        security=security,
        quality=quality,
        documentation=documentation,
        architecture=architecture,
        test_coverage=test_coverage,
        technical_debt=technical_debt,
        test_coverage_measured=include_tests,
    )
