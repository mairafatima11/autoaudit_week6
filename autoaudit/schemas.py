"""Shared data models. Every agent constructs Finding objects the same way
via `make_finding(...)`, which also produces the stable `fingerprint` used
by the persistent audit-history diffing (new/fixed/recurring)."""
from __future__ import annotations

import hashlib
import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def plain(value):
    """Return the plain string value of an enum-or-str field.

    `Finding`'s `use_enum_values` config only converts Enum -> str at
    construction time, not on later attribute assignment, and str-mixin
    Enums (e.g. `class X(str, Enum)`) pass `isinstance(x, str)` even when
    still holding the enum member, whose `str()` renders as
    "ClassName.MEMBER" rather than the value. Always route through this
    helper instead of an `isinstance(x, str)` check when reading or
    displaying these fields.
    """
    return value.value if isinstance(value, Enum) else value


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Category(str, Enum):
    SECURITY = "security"
    QUALITY = "quality"
    DOCS = "docs"


class FindingStatus(str, Enum):
    NEW = "new"
    RECURRING = "recurring"
    FIXED = "fixed"


class Finding(BaseModel):
    fingerprint: str
    file: str
    line: int = 0
    category: Category
    rule: str
    title: str
    description: str
    severity: Severity
    source_agent: str          # "security" | "quality"
    source_tool: str           # e.g. "semgrep" | "fallback-scanner" | "heuristic" | "llm"
    evidence: str = ""         # raw evidence snippet the claim is grounded in
    suggested_fix: Optional[str] = None
    status: FindingStatus = FindingStatus.NEW
    confidence: float = Field(default=0.3, ge=0.0, le=1.0)

    model_config = {"use_enum_values": True}


def make_fingerprint(file: str, line: int, category: str, rule: str) -> str:
    raw = f"{file}:{line}:{category}:{rule}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def make_finding(
    *,
    file: str,
    line: int,
    category: Category,
    rule: str,
    title: str,
    description: str,
    severity: Severity,
    source_agent: str,
    source_tool: str,
    evidence: str = "",
    suggested_fix: Optional[str] = None,
) -> Finding:
    return Finding(
        fingerprint=make_fingerprint(file, line, category.value if isinstance(category, Category) else category, rule),
        file=file,
        line=line,
        category=category,
        rule=rule,
        title=title,
        description=description,
        severity=severity,
        source_agent=source_agent,
        source_tool=source_tool,
        evidence=evidence,
        suggested_fix=suggested_fix,
    )


class ImpactLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FixProposal(BaseModel):
    """Output of the Fix Agent. Proposal-only — never applied automatically
    (see FixAgent docstring / prompts.md, Week 7 entry)."""

    finding_fingerprint: str
    file: str
    patch: str                      # unified diff text
    pr_title: str
    pr_description: str
    commit_message: str
    suggested_unit_test: str
    suggested_integration_test: str
    estimated_impact: ImpactLevel
    estimated_confidence: float = Field(ge=0.0, le=1.0)
    model_config = {"use_enum_values": True}


class DocGapKind(str, Enum):
    MISSING_DOCSTRING = "missing_docstring"
    MISSING_README_SECTION = "missing_readme_section"
    MISSING_COMMENT = "missing_comment"
    MISSING_API_DOC = "missing_api_doc"


class DocSuggestion(BaseModel):
    """Output of the Documentation Agent."""

    file: str
    line: int = 0
    kind: DocGapKind
    symbol: str = ""                # function/class/module name, if applicable
    suggestion: str                 # the generated documentation text
    rationale: str = ""
    model_config = {"use_enum_values": True}


class ReconciledFinding(BaseModel):
    """Supervisor reconciliation output: cross-checks findings that
    multiple agents raised (or nearly raised) about the same code."""

    primary_fingerprint: str
    file: str
    line: int
    contributing_agents: list[str]      # e.g. ["security", "quality"]
    agreement: bool                     # True if 2+ agents agree
    confidence: float = Field(ge=0.0, le=1.0)
    merged_explanation: str
    conflict: Optional[str] = None      # description of disagreement, if any
    priority: int = 5                   # 1 (highest) - 10 (lowest)


class ModelRunResult(BaseModel):
    provider: str
    model: str
    response: str
    latency_ms: float
    token_estimate: int
    confidence: float = Field(ge=0.0, le=1.0)
    error: Optional[str] = None


class ModelComparison(BaseModel):
    prompt: str
    results: list[ModelRunResult]
    agreement: bool
    differences: str
    merged_answer: str
    reasoning_summary: str = ""


class RepoHealthScore(BaseModel):
    """Week 7/8 dashboard input: 0-100 composite score plus category
    breakdown, derived from a single AuditReport's findings, documentation
    gaps and observed test signals. See analysis/health_score.py."""

    overall: int = Field(ge=0, le=100)
    security: int = Field(ge=0, le=100)
    quality: int = Field(ge=0, le=100)
    documentation: int = Field(ge=0, le=100)
    architecture: int = Field(ge=0, le=100)
    test_coverage: int = Field(ge=0, le=100)
    technical_debt: int = Field(ge=0, le=100)
    # False when the repository had no source files to judge, in which case
    # `test_coverage` is excluded from `overall` and the UI labels it as
    # "not measured" instead of showing a 0 the user can't act on. Defaults
    # to True so scores persisted before this field existed keep their old
    # meaning when read back.
    test_coverage_measured: bool = True


class TestCoverageDetail(BaseModel):
    """Observable test-suite signals behind `RepoHealthScore.test_coverage`
    — surfaced so the UI can show what was actually measured rather than
    presenting a heuristic as real line coverage."""

    measured: bool = False
    score: int = 0
    source_files: int = 0
    test_files: int = 0
    test_cases: int = 0
    source_symbols: int = 0
    modules_with_tests: int = 0
    module_coverage_pct: int = 0


class RepoProfile(BaseModel):
    """Framework/package-manager/directory profile — Repository Overview
    page data that isn't derivable from findings alone."""

    total_files: int = 0
    total_directories: int = 0
    package_manager: Optional[str] = None
    frameworks: list[str] = Field(default_factory=list)
    languages: dict[str, int] = Field(default_factory=dict)
    primary_language: Optional[str] = None


class AuditReport(BaseModel):
    run_id: str
    repo_id: str
    repo_source: str
    timestamp: float = Field(default_factory=time.time)
    findings: list[Finding] = Field(default_factory=list)
    files_scanned: int = 0
    chunks_indexed: int = 0
    is_first_run: bool = True
    doc_suggestions: list[DocSuggestion] = Field(default_factory=list)
    reconciled_findings: list[ReconciledFinding] = Field(default_factory=list)
    architecture_explanation: str = ""
    repo_profile: RepoProfile = Field(default_factory=RepoProfile)
    test_coverage: TestCoverageDetail = Field(default_factory=TestCoverageDetail)
    # How many findings/doc suggestions kept a heuristic or placeholder
    # description because every model provider was unavailable. A run with
    # a non-zero value here is complete and trustworthy in its *detection*
    # (which is deterministic) but has degraded prose; the UI says so
    # rather than presenting placeholders as model output.
    degraded_suggestions: int = 0

    def active_findings(self) -> list[Finding]:
        """Findings that still exist in the code.

        `findings` also carries `fixed` entries reconstructed by the
        audit-history diff for issues resolved since the previous run. They
        belong in the trend/comparison views, but counting them as current
        problems inflated the Dashboard's severity tiles and penalised the
        health score for work already done.
        """
        return [f for f in self.findings if plain(f.status) != "fixed"]

    def summary_counts(self, include_fixed: bool = False) -> dict:
        counts = {"high": 0, "medium": 0, "low": 0, "info": 0}
        source = self.findings if include_fixed else self.active_findings()
        for f in source:
            counts[plain(f.severity)] = counts.get(plain(f.severity), 0) + 1
        return counts

    def status_counts(self) -> dict:
        counts = {"new": 0, "recurring": 0, "fixed": 0}
        for f in self.findings:
            counts[plain(f.status)] = counts.get(plain(f.status), 0) + 1
        return counts
