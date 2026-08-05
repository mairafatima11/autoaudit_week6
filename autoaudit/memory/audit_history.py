"""Persistent Audit Memory: stores every run's findings keyed by a stable
fingerprint (file+line+category+rule), and diffs a new run's findings
against the immediately preceding run for the same repo so the Report
Agent can tag each finding new / recurring / fixed.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ..schemas import Finding, FindingStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    repo_source TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    run_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    category TEXT NOT NULL,
    rule TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    source_agent TEXT NOT NULL,
    source_tool TEXT NOT NULL,
    PRIMARY KEY (run_id, fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
"""


class AuditHistory:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        self.close()
    def last_run_id(self, repo_id: str, before_ts: float | None = None) -> str | None:
        query = "SELECT run_id FROM runs WHERE repo_id = ?"
        params: list = [repo_id]
        if before_ts is not None:
            query += " AND ts < ?"
            params.append(before_ts)
        query += " ORDER BY ts DESC LIMIT 1"
        cur = self.conn.execute(query, params)
        row = cur.fetchone()
        return row[0] if row else None

    def get_findings(self, run_id: str) -> dict[str, dict]:
        cur = self.conn.execute(
            "SELECT fingerprint, file, line, category, rule, title, severity FROM findings WHERE run_id = ?",
            (run_id,),
        )
        return {
            row[0]: {
                "file": row[1], "line": row[2], "category": row[3],
                "rule": row[4], "title": row[5], "severity": row[6],
            }
            for row in cur.fetchall()
        }

    def save_run(self, run_id: str, repo_id: str, repo_source: str, findings: list[Finding]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, repo_id, repo_source, ts) VALUES (?, ?, ?, ?)",
            (run_id, repo_id, repo_source, time.time()),
        )
        for f in findings:
            severity = f.severity if isinstance(f.severity, str) else f.severity.value
            category = f.category if isinstance(f.category, str) else f.category.value
            self.conn.execute(
                """INSERT OR REPLACE INTO findings
                   (run_id, fingerprint, file, line, category, rule, title, description, severity, source_agent, source_tool)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, f.fingerprint, f.file, f.line, category, f.rule, f.title,
                 f.description, severity, f.source_agent, f.source_tool),
            )
        self.conn.commit()

    def diff_against_last(self, repo_id: str, current_run_id: str, findings: list[Finding]) -> tuple[list[Finding], bool]:
        """Tag each finding new/recurring based on the previous run for this
        repo, and report whether this is the repo's first-ever run."""
        prev_run_id = self.last_run_id(repo_id)

        if prev_run_id is None:
            for f in findings:
                f.status = FindingStatus.NEW
            return findings, True

        prev = self.get_findings(prev_run_id)
        current_fps = {f.fingerprint for f in findings}
        for f in findings:

            f.status = (FindingStatus.RECURRING if f.fingerprint in prev else FindingStatus.NEW).value

        fixed: list[Finding] = []
        for fp, data in prev.items():
            if fp not in current_fps:
                fixed.append(
                    Finding(
                        fingerprint=fp,
                        file=data["file"],
                        line=data["line"],
                        category=data["category"],
                        rule=data["rule"],
                        title=data["title"],
                        description="Previously reported; not found in the latest scan.",
                        severity=data["severity"],
                        source_agent="audit-history",
                        source_tool="diff",
                        status=FindingStatus.FIXED,
                    )
                )
        return findings + fixed, False
