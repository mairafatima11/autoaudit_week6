"""Static analysis tool used by the Security Agent.

Uses Semgrep via subprocess if it's on PATH (real, industry-standard
scanning). Otherwise falls back to a small, deterministic regex-based
scanner so the Security Agent still produces grounded, verifiable evidence
with zero extra dependencies — this fallback is also what the offline test
suite exercises.

Every raw finding carries `source_tool` so downstream reporting can show
"verifiable, not just asserted" provenance, per the proposal's risk table.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class RawFinding:
    file: str
    line: int
    rule: str
    message: str
    severity: str         
    evidence: str
    source_tool: str    


def semgrep_available() -> bool:
    return shutil.which("semgrep") is not None


def run_semgrep(root_path: str) -> list[RawFinding]:
    proc = subprocess.run(
        ["semgrep", "--config=auto", "--json", "--quiet", root_path],
        capture_output=True,
        text=True,
        timeout=300,
    )
    findings: list[RawFinding] = []
    if not proc.stdout:
        return findings
    data = json.loads(proc.stdout)
    for r in data.get("results", []):
        """import pprint

        pprint.pp(r["extra"])
        break"""
        sev_raw = (r.get("extra", {}) or {}).get("severity", "WARNING").upper()
        severity = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}.get(sev_raw, "medium")
        try:
            relative_file = (
                Path(r.get("path", ""))
                .resolve()
                .relative_to(Path(root_path).resolve())
                .as_posix()
            )
        except ValueError:
            relative_file = Path(r.get("path", "")).name
        extra = r.get("extra", {}) or {}

        evidence = (
            extra.get("lines")
            or ""
            ).strip()
        findings.append(
            RawFinding(
                file=relative_file,
                line=int((r.get("start", {}) or {}).get("line", 0)),
                rule=r.get("check_id", "semgrep-rule"),
                message=(r.get("extra", {}) or {}).get("message", "Semgrep finding"),
                severity=severity,
                evidence=evidence,
                source_tool="semgrep",
            )
        )
    return findings



_FALLBACK_RULES: list[tuple[str, re.Pattern, str, str]] = [
    (
        "hardcoded-secret",
        re.compile(
            r"""(?i)\b(api[_-]?key|secret|password|token|access[_-]?key)\s*[:=]\s*["'][A-Za-z0-9\-_/+=]{6,}["']"""
        ),
        "Possible hardcoded secret",
        "high",
    ),
    (
        "dangerous-eval",
        re.compile(r"\b(eval|exec)\s*\("),
        "Use of eval()/exec() on dynamic input",
        "high",
    ),
    (
        "sql-string-concat",
        re.compile(r"""(?i)(select|insert|update|delete)\b.{0,80}["']\s*\+\s*\w"""),
        "SQL statement built via string concatenation (possible injection)",
        "high",
    ),
    (
        "insecure-yaml-load",
        re.compile(r"\byaml\.load\s*\((?!.*Loader=)"),
        "yaml.load() without a safe Loader",
        "medium",
    ),
    (
        "broad-except",
        re.compile(r"\bexcept\s*:\s*$"),
        "Bare except clause swallows all errors",
        "low",
    ),
]


def run_fallback_scanner(files: list[tuple[str, str]]) -> list[RawFinding]:
    """`files` is a list of (relative_path, content)."""
    findings: list[RawFinding] = []
    for path, content in files:
        lines = content.splitlines()
        for lineno, line in enumerate(lines, start=1):
            for rule_id, pattern, message, severity in _FALLBACK_RULES:
                if pattern.search(line):
                    findings.append(
                        RawFinding(
                            file=path,
                            line=lineno,
                            rule=rule_id,
                            message=message,
                            severity=severity,
                            evidence=line.strip()[:200],
                            source_tool="fallback-scanner",
                        )
                    )
    return findings


def scan(root_path: str, files: list[tuple[str, str]]) -> list[RawFinding]:
    """Entry point used by the Security Agent. Tries Semgrep first."""
    findings: list[RawFinding] = []
    if semgrep_available():
        try:
            findings.extend(run_semgrep(root_path))
        except Exception:

            pass
    findings.extend(run_fallback_scanner(files))

    return findings
