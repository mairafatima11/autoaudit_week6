"""Report Agent: merges Security + Quality findings, dedupes by
(file, line) before ranking, diffs against audit history for new/fixed/
recurring status, and renders the final Markdown report.

Note: cross-agent *reconciliation* (confidence scoring when Security and
Quality overlap) is Week 7 scope per the proposal — this agent only dedupes
exact (file, line, rule) collisions within a single run.
"""
from __future__ import annotations

from ..memory.audit_history import AuditHistory
from ..schemas import AuditReport, Finding, plain as _plain

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


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

        self.audit_history.save_run(
            run_id, repo_id, repo_source, deduped,
            files_scanned=files_scanned, chunks_indexed=chunks_indexed,
        )

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
    def render_pdf(report: AuditReport, health_score=None) -> bytes:
        """Render a presentation-ready PDF: cover summary, health score
        breakdown, trend vs. previous run, and a findings table colored by
        severity. Built with reportlab/platypus (see docs/DEVELOPER_GUIDE.md
        for why: no headless-browser dependency needed for HTML->PDF)."""
        import io

        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            KeepTogether,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        SEVERITY_COLOR = {
            "high": colors.HexColor("#F0495C"),
            "medium": colors.HexColor("#F5A623"),
            "low": colors.HexColor("#E8C34D"),
            "info": colors.HexColor("#59B9B0"),
        }
        INK = colors.HexColor("#0A0E13")
        PANEL = colors.HexColor("#F4F6F8")
        FOG = colors.HexColor("#4A5560")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=letter,
            topMargin=0.75 * inch, bottomMargin=0.75 * inch,
            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
            title=f"AutoAudit AI Report — {report.repo_source}",
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("AATitle", parent=styles["Title"], textColor=INK, fontSize=22, spaceAfter=4)
        meta_style = ParagraphStyle("AAMeta", parent=styles["Normal"], textColor=FOG, fontSize=9)
        h2_style = ParagraphStyle("AAH2", parent=styles["Heading2"], textColor=INK, spaceBefore=18, spaceAfter=8)
        body_style = ParagraphStyle("AABody", parent=styles["Normal"], textColor=INK, fontSize=9, leading=13, alignment=TA_LEFT)
        finding_title_style = ParagraphStyle("AAFindingTitle", parent=styles["Normal"], textColor=INK, fontSize=10, leading=13, fontName="Helvetica-Bold")
        mono_style = ParagraphStyle("AAMono", parent=styles["Normal"], textColor=FOG, fontSize=8, fontName="Courier", leading=11)

        story = []
        story.append(Paragraph("AutoAudit AI", title_style))
        story.append(Paragraph(f"Audit Report — {report.repo_source}", ParagraphStyle("sub", parent=styles["Heading2"], textColor=FOG, fontSize=13)))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"Run ID: {report.run_id} &nbsp;·&nbsp; Files scanned: {report.files_scanned} &nbsp;·&nbsp; "
            f"Chunks indexed: {report.chunks_indexed} &nbsp;·&nbsp; "
            f"{'First run for this repository' if report.is_first_run else 'Compared against previous run'}",
            meta_style,
        ))
        story.append(Spacer(1, 14))

        counts = report.summary_counts()
        summary_data = [["Severity", "Count"]] + [
            [sev.capitalize(), str(counts[sev])] for sev in ("high", "medium", "low", "info")
        ]
        summary_table = Table(summary_data, colWidths=[2.5 * inch, 1.5 * inch])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), INK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PANEL]),
            ("TEXTCOLOR", (0, 1), (0, 1), SEVERITY_COLOR["high"]),
            ("TEXTCOLOR", (0, 2), (0, 2), SEVERITY_COLOR["medium"]),
            ("TEXTCOLOR", (0, 3), (0, 3), SEVERITY_COLOR["low"]),
            ("TEXTCOLOR", (0, 4), (0, 4), SEVERITY_COLOR["info"]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D5DBE0")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(Paragraph("Summary", h2_style))
        story.append(summary_table)

        if health_score is not None:
            hs = health_score.model_dump() if hasattr(health_score, "model_dump") else health_score
            story.append(Paragraph("Repository Health Score", h2_style))
            health_data = [["Category", "Score"]] + [
                [k.replace("_", " ").title(), f"{v}/100"]
                for k, v in hs.items()
            ]
            health_table = Table(health_data, colWidths=[2.5 * inch, 1.5 * inch])
            health_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PANEL]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D5DBE0")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(health_table)

        if not report.is_first_run:
            new_n = sum(1 for f in report.findings if _plain(f.status) == "new")
            recurring_n = sum(1 for f in report.findings if _plain(f.status) == "recurring")
            fixed_n = sum(1 for f in report.findings if _plain(f.status) == "fixed")
            story.append(Paragraph("Trend vs. Previous Run", h2_style))
            story.append(Paragraph(f"New: {new_n} &nbsp;·&nbsp; Recurring: {recurring_n} &nbsp;·&nbsp; Fixed since last run: {fixed_n}", body_style))

        story.append(Paragraph("Findings", h2_style))
        if not report.findings:
            story.append(Paragraph("No findings.", body_style))
        else:
            for i, f in enumerate(report.findings, start=1):
                sev = _plain(f.severity)
                status = _plain(f.status)
                color = SEVERITY_COLOR.get(sev, FOG)
                block = [
                    Table(
                        [[Paragraph(f"{i}. {f.title}", finding_title_style),
                          Paragraph(f"<b>{sev.upper()}</b>", ParagraphStyle("sev", parent=body_style, textColor=color, alignment=2))]],
                        colWidths=[5.0 * inch, 1.0 * inch],
                    ),
                    Paragraph(f"{f.file}:{f.line} &nbsp;·&nbsp; rule: {f.rule} &nbsp;·&nbsp; via {f.source_agent} ({f.source_tool}) &nbsp;·&nbsp; status: {status}", mono_style),
                    Spacer(1, 3),
                    Paragraph(f.description or "", body_style),
                ]
                if f.evidence:
                    block.append(Spacer(1, 3))
                    block.append(Paragraph(f"Evidence: {f.evidence}", mono_style))
                if f.suggested_fix:
                    block.append(Spacer(1, 3))
                    block.append(Paragraph(f"Suggested fix: {f.suggested_fix}", body_style))
                block.append(Spacer(1, 12))
                story.append(KeepTogether(block))

        doc.build(story)
        return buffer.getvalue()

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
