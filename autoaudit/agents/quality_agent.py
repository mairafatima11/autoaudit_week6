"""Quality Agent: flags code smells (long functions, missing docstrings,
near-duplicate code blocks) via simple heuristics plus vector-similarity
retrieval, then uses Gemini to phrase each as a finding. Runs on a second
model deliberately, so its output can later be cross-checked against the
Security Agent's (Week 7 reconciliation scope).
"""
from __future__ import annotations

from ..llm.base import LLMClient
from ..memory.vector_store import VectorStore
from ..schemas import Category, Finding, Severity, make_finding
from ..tools.repo_reader import FileRecord
from ..tracing import Tracer

SYSTEM_PROMPT = (
    "You are a pragmatic code-quality reviewer. Given one code-smell "
    "heuristic result, write a 1-2 sentence, non-alarmist note explaining "
    "the smell and a concrete suggestion to improve it."
)

PY_DOC_TRIGGER = ("def ", "class ")


class QualityAgent:
    def __init__(
        self,
        llm: LLMClient,
        vector_store: VectorStore,
        tracer: Tracer,
        long_function_threshold: int = 40,
    ) -> None:
        self.llm = llm
        self.vector_store = vector_store
        self.tracer = tracer
        self.long_function_threshold = long_function_threshold

    def run(self, repo_id: str, files: list[FileRecord]) -> list[Finding]:
        self.tracer.log("quality_agent", "scan.start", repo_id=repo_id, files=len(files))
        findings: list[Finding] = []
        
        findings.extend(self._long_functions(files))
        findings.extend(self._missing_docstrings(files))
        findings.extend(self._duplicate_code(repo_id))

        self.tracer.log("quality_agent", "scan.done", findings=len(findings))
        return findings

    def _phrase(self, heuristic_summary: str) -> str:
        return self.llm.complete(heuristic_summary, system=SYSTEM_PROMPT)

    def _long_functions(self, files: list[FileRecord]) -> list[Finding]:
        out: list[Finding] = []
        for rec in files:
            if rec.language != "python":
                continue
            for chunk in rec.chunks:
                n_lines = chunk.text.count("\n") + 1
                if n_lines > self.long_function_threshold and chunk.text.lstrip().startswith(("def ", "async def ")):
                    summary = (
                        f"Function starting at {rec.path}:{chunk.start_line} is {n_lines} lines long "
                        f"(threshold {self.long_function_threshold}). Consider splitting it."
                    )
                    out.append(
                        make_finding(
                            file=rec.path,
                            line=chunk.start_line,
                            category=Category.QUALITY,
                            rule="long-function",
                            title=f"Long function ({n_lines} lines)",
                            description=self._phrase(summary),
                            severity=Severity.LOW,
                            source_agent="quality",
                            source_tool="heuristic",
                            evidence=chunk.text.splitlines()[0][:200],
                        )
                    )
        return out

    def _missing_docstrings(self, files: list[FileRecord]) -> list[Finding]:
        out: list[Finding] = []
        for rec in files:
            if rec.language != "python":
                continue
            for chunk in rec.chunks:
                stripped = chunk.text.lstrip()
                if not stripped.startswith(PY_DOC_TRIGGER):
                    continue
                if stripped.startswith("def _") or stripped.startswith("class _"):
                    continue  
                lines = chunk.text.splitlines()
                body = lines[1:3]
                has_doc = any('"""' in ln or "'''" in ln for ln in body)
                if has_doc:
                    continue
                signature = lines[0].strip()
                summary = f"Public symbol `{signature}` at {rec.path}:{chunk.start_line} has no docstring."
                out.append(
                    make_finding(
                        file=rec.path,
                        line=chunk.start_line,
                        category=Category.QUALITY,
                        rule="missing-docstring",
                        title="Missing docstring on public symbol",
                        description=self._phrase(summary),
                        severity=Severity.INFO,
                        source_agent="quality",
                        source_tool="heuristic",
                        evidence=signature[:200],
                    )
                )
        return out

    def _duplicate_code(self, repo_id: str) -> list[Finding]:
        out: list[Finding] = []
        for a, b in self.vector_store.similar_chunks(repo_id, min_score=0.92):
            summary = (
                f"Code at {a['file']}:{a['start_line']} looks nearly identical to "
                f"{b['file']}:{b['start_line']}. Consider extracting a shared helper."
            )
            out.append(
                make_finding(
                    file=a["file"],
                    line=a["start_line"],
                    category=Category.QUALITY,
                    rule="duplicate-code",
                    title=f"Possible duplicate of {b['file']}:{b['start_line']}",
                    description=self._phrase(summary),
                    severity=Severity.LOW,
                    source_agent="quality",
                    source_tool="heuristic",
                    evidence=a["text"].splitlines()[0][:200],
                )
            )
        return out
