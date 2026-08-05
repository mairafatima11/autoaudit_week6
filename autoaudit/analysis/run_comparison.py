"""Audit Run Comparison (Week 8): compares any two audit runs and reports
newly introduced / fixed / recurring findings, severity changes, and a
Repository Health Score delta.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..memory.audit_history import AuditHistory
from ..schemas import AuditReport, RepoHealthScore
from .health_score import compute_health_score


class RunComparison(BaseModel):
    run_a: str
    run_b: str
    new_findings: list[dict]
    fixed_findings: list[dict]
    recurring_findings: list[dict]
    severity_changes: list[dict]
    health_score_a: RepoHealthScore
    health_score_b: RepoHealthScore
    health_score_delta: int
    trend_summary: str


def compare_runs(audit_history: AuditHistory, run_a: str, run_b: str) -> RunComparison:
    diff = audit_history.diff_between_runs(run_a, run_b)
    a_findings, b_findings = diff["run_a_findings"], diff["run_b_findings"]

    new_findings = [b_findings[fp] | {"fingerprint": fp} for fp in diff["new_in_b"]]
    fixed_findings = [a_findings[fp] | {"fingerprint": fp} for fp in diff["fixed_since_a"]]

    severity_changes = []
    recurring_findings = []
    for fp in diff["recurring"]:
        a, b = a_findings[fp], b_findings[fp]
        entry = b | {"fingerprint": fp}
        recurring_findings.append(entry)
        if a["severity"] != b["severity"]:
            severity_changes.append(
                {"fingerprint": fp, "file": b["file"], "line": b["line"],
                 "from_severity": a["severity"], "to_severity": b["severity"]}
            )

    score_a = _resolve_health_score(audit_history, run_a)
    score_b = _resolve_health_score(audit_history, run_b)

    delta = score_b.overall - score_a.overall
    if delta > 0:
        trend = f"Repository health improved by {delta} points."
    elif delta < 0:
        trend = f"Repository health declined by {abs(delta)} points."
    else:
        trend = "Repository health is unchanged."
    if new_findings:
        trend += f" {len(new_findings)} new finding(s) introduced."
    if fixed_findings:
        trend += f" {len(fixed_findings)} finding(s) fixed."

    return RunComparison(
        run_a=run_a, run_b=run_b,
        new_findings=new_findings, fixed_findings=fixed_findings,
        recurring_findings=recurring_findings, severity_changes=severity_changes,
        health_score_a=score_a, health_score_b=score_b, health_score_delta=delta,
        trend_summary=trend,
    )


def _resolve_health_score(audit_history: AuditHistory, run_id: str) -> RepoHealthScore:
    """Prefer the health score persisted when the run actually completed
    (real files_scanned + doc_suggestions). Falls back to recomputing from
    reconstructed findings only for runs saved before this was persisted —
    that recompute is a strictly worse approximation (documentation is
    pegged at 100, files_scanned is guessed from finding count), so it's
    a fallback, not the primary path."""
    stored = audit_history.get_health_score(run_id)
    if stored is not None:
        return stored
    findings = audit_history.get_findings_full(run_id)
    meta = next((r for r in audit_history.list_runs() if r["run_id"] == run_id), None)
    files_scanned = (meta or {}).get("files_scanned") or max(len({f.file for f in findings}), 1)
    report = AuditReport(
        run_id=run_id, repo_id="", repo_source="",
        findings=findings, files_scanned=files_scanned,
    )
    return compute_health_score(report)
