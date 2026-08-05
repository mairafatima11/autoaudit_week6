"""Shared data models. Every agent constructs Finding objects the same way
via `make_finding(...)`, which also produces the stable `fingerprint` used
by the persistent audit-history diffing (new/fixed/recurring)."""
from __future__ import annotations

import hashlib
import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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


class AuditReport(BaseModel):
    run_id: str
    repo_id: str
    repo_source: str
    timestamp: float = Field(default_factory=time.time)
    findings: list[Finding] = Field(default_factory=list)
    files_scanned: int = 0
    chunks_indexed: int = 0
    is_first_run: bool = True

    def summary_counts(self) -> dict:
        counts = {"high": 0, "medium": 0, "low": 0, "info": 0}
        for f in self.findings:
            sev = f.severity.value if isinstance(f.severity, Severity) else f.severity
            counts[sev] = counts.get(sev, 0) + 1
        return counts
