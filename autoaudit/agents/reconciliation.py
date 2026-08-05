"""Supervisor reconciliation (Week 7): compares findings across agents
(Security, Quality, Repository) to detect agreement/disagreement on the
same code location, assign a merged confidence score, and rank priority.

Two findings are considered "about the same thing" if they hit the same
file and are within `line_window` lines of each other — agents chunk code
differently, so exact line matches would under-count real overlap.
"""
from __future__ import annotations

from ..schemas import Finding, ReconciledFinding

_SEVERITY_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4, "info": 0.2}


def _plain(value) -> str:
    return value.value if hasattr(value, "value") else value


class ReconciliationEngine:
    def __init__(self, line_window: int = 3) -> None:
        self.line_window = line_window

    def reconcile(self, findings: list[Finding]) -> list[ReconciledFinding]:
        groups = self._group_overlapping(findings)
        reconciled = [self._merge_group(group) for group in groups]
        reconciled.sort(key=lambda r: r.priority)
        return reconciled

    def confidence_by_fingerprint(self, findings: list[Finding]) -> dict[str, float]:
        """Same grouping/confidence logic as `reconcile`, but returns a
        fingerprint -> confidence map covering every finding (not just each
        group's primary) — every member of an agreeing group gets that
        group's confidence, since cross-agent agreement is evidence for the
        whole group, not only its highest-severity member."""
        groups = self._group_overlapping(findings)
        result: dict[str, float] = {}
        for group in groups:
            merged = self._merge_group(group)
            for f in group:
                result[f.fingerprint] = merged.confidence
        return result

    # ---- grouping --------------------------------------------------------

    def _group_overlapping(self, findings: list[Finding]) -> list[list[Finding]]:
        by_file: dict[str, list[Finding]] = {}
        for f in findings:
            by_file.setdefault(f.file, []).append(f)

        groups: list[list[Finding]] = []
        for file_findings in by_file.values():
            file_findings.sort(key=lambda f: f.line)
            current: list[Finding] = []
            last_line = None
            for f in file_findings:
                if current and last_line is not None and f.line - last_line <= self.line_window:
                    current.append(f)
                else:
                    if current:
                        groups.append(current)
                    current = [f]
                last_line = f.line
            if current:
                groups.append(current)
        return groups

    # ---- merging -----------------------------------------------------------

    def _merge_group(self, group: list[Finding]) -> ReconciledFinding:
        primary = max(
            group, key=lambda f: _SEVERITY_WEIGHT.get(_plain(f.severity), 0.0)
        )
        agents = sorted({f.source_agent for f in group})
        agreement = len(agents) >= 2

        # Confidence: base severity weight of the strongest finding, boosted
        # by cross-agent agreement, dampened by conflicting severities.
        base = _SEVERITY_WEIGHT.get(_plain(primary.severity), 0.3)
        severities = {_plain(f.severity) for f in group}
        conflict = None
        confidence = base

        if agreement:
            confidence = min(1.0, base + 0.2 * (len(agents) - 1))
            if len(severities) > 1:
                conflict = (
                    f"Agents disagree on severity: "
                    + ", ".join(f"{f.source_agent}={_plain(f.severity)}" for f in group)
                )
                confidence = max(0.1, confidence - 0.15)
        else:
            confidence = max(0.1, base - 0.1)  # single-agent findings are less certain

        explanations = "; ".join(
            f"[{f.source_agent}] {f.description}".strip() for f in group if f.description
        )
        merged_explanation = explanations[:800] if explanations else primary.description

        priority = self._priority(primary, agreement, confidence)

        return ReconciledFinding(
            primary_fingerprint=primary.fingerprint,
            file=primary.file,
            line=primary.line,
            contributing_agents=agents,
            agreement=agreement,
            confidence=round(confidence, 2),
            merged_explanation=merged_explanation,
            conflict=conflict,
            priority=priority,
        )

    @staticmethod
    def _priority(primary: Finding, agreement: bool, confidence: float) -> int:
        """1 = highest priority, 10 = lowest. High severity + multi-agent
        agreement + high confidence sorts first."""
        sev_rank = {"high": 0, "medium": 3, "low": 6, "info": 8}.get(_plain(primary.severity), 5)
        bonus = -1 if agreement else 0
        confidence_penalty = round((1 - confidence) * 2)
        return max(1, min(10, sev_rank + bonus + confidence_penalty))
