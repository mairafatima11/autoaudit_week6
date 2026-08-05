"""Persistent Audit Memory: stores every run's findings keyed by a stable
fingerprint (file+line+category+rule), and diffs a new run's findings
against the immediately preceding run for the same repo so the Report
Agent can tag each finding new / recurring / fixed.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ..schemas import Finding, FindingStatus, RepoHealthScore  # noqa: F401 (RepoHealthScore used in list_runs)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    repo_source TEXT NOT NULL,
    ts REAL NOT NULL,
    health_score_json TEXT,
    files_scanned INTEGER,
    chunks_indexed INTEGER
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
        # Migrations for DBs created before these columns existed — CREATE
        # TABLE IF NOT EXISTS above is a no-op on an already-existing `runs`
        # table, so older DB files need each column added explicitly.
        existing_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(runs)")}
        for column, ddl in (
            ("health_score_json", "TEXT"),
            ("files_scanned", "INTEGER"),
            ("chunks_indexed", "INTEGER"),
        ):
            if column not in existing_cols:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {ddl}")
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

    def save_run(
        self,
        run_id: str,
        repo_id: str,
        repo_source: str,
        findings: list[Finding],
        files_scanned: int | None = None,
        chunks_indexed: int | None = None,
    ) -> None:
        """Persist a run. `files_scanned`/`chunks_indexed` are stored so the
        Memory page can show real knowledge-base sizes for historical runs —
        previously these lived only on the in-memory `AuditReport`, so any
        run whose job had aged out of the process reported 0 chunks indexed
        and a files count guessed from the number of distinct finding paths."""
        self.conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, repo_id, repo_source, ts, files_scanned, chunks_indexed)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, repo_id, repo_source, time.time(), files_scanned, chunks_indexed),
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

    def save_health_score(self, run_id: str, health: RepoHealthScore) -> None:
        """Persist the exact health score computed for a completed run
        (including its real `files_scanned` and doc-coverage signal), so
        Run Comparison can reuse it later instead of recomputing a
        different, inconsistent score from reconstructed findings alone
        (see `analysis/run_comparison.py`)."""
        self.conn.execute(
            "UPDATE runs SET health_score_json = ? WHERE run_id = ?",
            (health.model_dump_json(), run_id),
        )
        self.conn.commit()

    def get_health_score(self, run_id: str) -> RepoHealthScore | None:
        cur = self.conn.execute("SELECT health_score_json FROM runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return None
        return RepoHealthScore.model_validate_json(row[0])

    def list_runs(self, repo_id: str | None = None) -> list[dict]:
        """All recorded runs, most recent first — powers the Trend
        Dashboard / Repository Timeline (Week 7/8).

        Includes each run's persisted health score, finding count and
        knowledge-base size so the Memory page can render the whole timeline
        from one request instead of issuing an N+1 fan-out of
        `GET /api/audits/{run_id}` (one per run) just to read a few numbers
        off each report.
        """
        base = """
            SELECT r.run_id, r.repo_id, r.repo_source, r.ts,
                   r.health_score_json, r.files_scanned, r.chunks_indexed,
                   (SELECT COUNT(*) FROM findings f WHERE f.run_id = r.run_id),
                   (SELECT COUNT(*) FROM findings f WHERE f.run_id = r.run_id AND f.severity = 'high'),
                   (SELECT COUNT(*) FROM findings f WHERE f.run_id = r.run_id AND f.severity = 'medium'),
                   (SELECT COUNT(*) FROM findings f WHERE f.run_id = r.run_id AND f.severity = 'low'),
                   (SELECT COUNT(*) FROM findings f WHERE f.run_id = r.run_id AND f.severity = 'info')
            FROM runs r
        """
        if repo_id:
            cur = self.conn.execute(base + " WHERE r.repo_id = ? ORDER BY r.ts DESC", (repo_id,))
        else:
            cur = self.conn.execute(base + " ORDER BY r.ts DESC")

        runs = []
        for r in cur.fetchall():
            health = None
            if r[4]:
                try:
                    health = RepoHealthScore.model_validate_json(r[4]).model_dump()
                except ValueError:
                    health = None
            runs.append({
                "run_id": r[0], "repo_id": r[1], "repo_source": r[2], "ts": r[3],
                "health_score": health,
                "files_scanned": r[5], "chunks_indexed": r[6],
                "finding_count": r[7],
                "severity_counts": {"high": r[8], "medium": r[9], "low": r[10], "info": r[11]},
            })
        return runs

    def repositories(self) -> list[dict]:
        """One row per audited repository, for the Memory page's repository
        selector. Trends were previously charted across *every* run in the
        database regardless of repository, so a flask run and a two-file
        toy repo sat next to each other on the same health-score line and
        the "trend" was really just repo-to-repo variance."""
        cur = self.conn.execute(
            """SELECT repo_id, repo_source, COUNT(*), MIN(ts), MAX(ts)
               FROM runs GROUP BY repo_id ORDER BY MAX(ts) DESC"""
        )
        return [
            {"repo_id": r[0], "repo_source": r[1], "run_count": r[2],
             "first_run_ts": r[3], "last_run_ts": r[4]}
            for r in cur.fetchall()
        ]

    def recurring_findings(self, repo_id: str, min_runs: int = 2) -> list[dict]:
        """Findings seen in at least `min_runs` distinct runs of one repo —
        the "what keeps coming back" view the Memory page is supposed to
        show. Computed in SQL over the whole history rather than inferred
        from a single pairwise run diff, so an issue that was fixed and then
        reintroduced still shows up as recurring."""
        cur = self.conn.execute(
            """SELECT f.fingerprint, COUNT(DISTINCT f.run_id) AS runs,
                      MAX(f.file), MAX(f.line), MAX(f.category), MAX(f.rule),
                      MAX(f.title), MAX(f.severity), MAX(r.ts)
               FROM findings f
               JOIN runs r ON r.run_id = f.run_id
               WHERE r.repo_id = ?
               GROUP BY f.fingerprint
               HAVING runs >= ?
               ORDER BY runs DESC, MAX(r.ts) DESC""",
            (repo_id, min_runs),
        )
        return [
            {"fingerprint": r[0], "run_count": r[1], "file": r[2], "line": r[3],
             "category": r[4], "rule": r[5], "title": r[6], "severity": r[7],
             "last_seen_ts": r[8]}
            for r in cur.fetchall()
        ]

    def get_findings_full(self, run_id: str) -> list[Finding]:
        """Reconstruct Finding objects for a historical run. Note: `status`
        (new/recurring/fixed) is computed live at report-build time and is
        not persisted per-run, so reconstructed findings default to NEW —
        callers wanting accurate historical status should use
        `diff_between_runs` instead of this directly."""
        cur = self.conn.execute(
            """SELECT fingerprint, file, line, category, rule, title, description,
                      severity, source_agent, source_tool FROM findings WHERE run_id = ?""",
            (run_id,),
        )
        return [
            Finding(
                fingerprint=row[0], file=row[1], line=row[2], category=row[3], rule=row[4],
                title=row[5], description=row[6], severity=row[7], source_agent=row[8],
                source_tool=row[9], status=FindingStatus.NEW,
            )
            for row in cur.fetchall()
        ]

    def diff_between_runs(self, run_a: str, run_b: str) -> dict:
        """Compare two arbitrary runs (Week 8 Audit Run Comparison), not
        necessarily consecutive. Returns fingerprints newly introduced in
        `run_b`, fixed since `run_a`, and recurring in both."""
        a = self.get_findings(run_a)
        b = self.get_findings(run_b)
        a_fps, b_fps = set(a.keys()), set(b.keys())
        return {
            "new_in_b": sorted(b_fps - a_fps),
            "fixed_since_a": sorted(a_fps - b_fps),
            "recurring": sorted(a_fps & b_fps),
            "run_a_findings": a,
            "run_b_findings": b,
        }

    def diff_against_last(self, repo_id: str, current_run_id: str, findings: list[Finding]) -> tuple[list[Finding], bool]:
        """Tag each finding new/recurring based on the previous run for this
        repo, and report whether this is the repo's first-ever run."""
        prev_run_id = self.last_run_id(repo_id)

        # Assign the plain `.value`, not the enum member: `Finding` uses
        # `use_enum_values`, which only converts on construction — a later
        # attribute assignment leaves the member in place, and because
        # `FindingStatus` is a str-mixin enum it then passes `isinstance(x,
        # str)` while rendering as "FindingStatus.NEW". The two branches
        # below previously disagreed on this, so a repo's first run carried
        # enum members and every later run carried strings.
        if prev_run_id is None:
            for f in findings:
                f.status = FindingStatus.NEW.value
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
