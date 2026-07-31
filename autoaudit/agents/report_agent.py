"""Report Agent: merges Security + Quality findings, dedupes by
(file, line) before ranking, diffs against audit history for new/fixed/
recurring status, and renders the final Markdown report.

Note: cross-agent *reconciliation* (confidence scoring when Security and
Quality overlap) is Week 7 scope per the proposal — this agent only dedupes
exact (file, line, rule) collisions within a single run.
"""
from __future__ import annotations

from enum import Enum

from ..memory.audit_history import AuditHistory
from ..schemas import AuditReport, Finding

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _plain(value) -> str:
    """Return the plain string value of an enum-or-str field.

    `Finding`'s `use_enum_values` config only converts Enum -> str at
    construction time, not on later attribute assignment, and str-mixin
    Enums (e.g. `class X(str, Enum)`) pass `isinstance(x, str)` even when
    still holding the enum member, whose `str()` renders as
    "ClassName.MEMBER" rather than the value. Always route through this
    helper instead of an `isinstance(x, str)` check when displaying these
    fields.
    """
    return value.value if isinstance(value, Enum) else value


class ReportAgent:
    def __init__(self, audit_history: AuditHistory) -> None:
        self.audit_history = audit_history

    def build_report(
        self,
        run_id: str,
        repo_id: str,
        repo_source: str,
        findings: list[Finding],
        files_scanned: int,
        chunks_indexed: int,
    ) -> AuditReport:
        deduped = self._dedupe(findings)

        tagged, is_first_run = self.audit_history.diff_against_last(repo_id, run_id, deduped)
        tagged.sort(key=lambda f: (_SEVERITY_ORDER.get(_plain(f.severity), 9), f.file, f.line))


        self.audit_history.save_run(run_id, repo_id, repo_source, deduped)

        return AuditReport(
            run_id=run_id,
            repo_id=repo_id,
            repo_source=repo_source,
            findings=tagged,
            files_scanned=files_scanned,
            chunks_indexed=chunks_indexed,
            is_first_run=is_first_run,
        )

    @staticmethod
    def _dedupe(findings: list[Finding]) -> list[Finding]:
        seen: dict[str, Finding] = {}
        for f in findings:
            seen.setdefault(f.fingerprint, f)
        return list(seen.values())

    @staticmethod
    def render_markdown(report: AuditReport) -> str:
        counts = report.summary_counts()
        lines = [
            f"# AutoAudit AI Report — `{report.repo_source}`",
            "",
            f"- Run ID: `{report.run_id}`",
            f"- Files scanned: {report.files_scanned}",
            f"- Chunks indexed (knowledge base): {report.chunks_indexed}",
            f"- {'First run for this repo.' if report.is_first_run else 'Compared against previous run.'}",
            "",
            "## Summary",
            "",
            f"- 🔴 High: {counts['high']}",
            f"- 🟠 Medium: {counts['medium']}",
            f"- 🟡 Low: {counts['low']}",
            f"- ⚪ Info: {counts['info']}",
            "",
        ]

        if not report.is_first_run:
            new_n = sum(1 for f in report.findings if _plain(f.status) == "new")
            recurring_n = sum(1 for f in report.findings if _plain(f.status) == "recurring")
            fixed_n = sum(1 for f in report.findings if _plain(f.status) == "fixed")
            lines += [
                "## Trend vs. previous run",
                "",
                f"- 🆕 New: {new_n}",
                f"- 🔁 Recurring: {recurring_n}",
                f"- ✅ Fixed since last run: {fixed_n}",
                "",
            ]

        lines += ["## Findings", ""]
        if not report.findings:
            lines.append("No findings. 🎉")
        else:
            for i, f in enumerate(report.findings, start=1):
                sev = _plain(f.severity)
                status = _plain(f.status)
                badge = {"new": "🆕", "recurring": "🔁", "fixed": "✅"}.get(status, "")
                lines += [
                    f"### {i}. [{sev.upper()}] {f.title} {badge}",
                    f"- **File:** `{f.file}:{f.line}`",
                    f"- **Category:** {_plain(f.category)}"
                    f" | **Source:** {f.source_agent} ({f.source_tool})"
                    f" | **Status:** {status}",
                    f"- **Rule:** `{f.rule}`",
                    f"- **Description:** {f.description}",
                ]
                if f.evidence:
                    lines.append(f"- **Evidence:** `{f.evidence}`")
                if f.suggested_fix:
                    lines.append(f"- **Suggested fix:** {f.suggested_fix}")
                lines.append("")

        return "\n".join(lines)
