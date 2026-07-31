"""Security Agent: runs static analysis (Semgrep, or the offline fallback
scanner) and uses Claude to turn each raw finding into a human-readable,
context-aware description, grounded in the retrieved code chunk from the
Repository Knowledge Base.
"""
from __future__ import annotations

from ..llm.base import LLMClient
from ..memory.vector_store import VectorStore
from ..schemas import Category, Finding, Severity, make_finding
from ..tools import static_analysis
from ..tools.repo_reader import FileRecord
from ..tools.source_utils import extract_source_snippet
from ..tracing import Tracer


SYSTEM_PROMPT = (
    "You are a precise, conservative application-security reviewer. "
    "Given one static-analysis finding and its surrounding code, explain in "
    "1-2 sentences why it's risky and what a safe fix looks like. Do not "
    "invent details not present in the evidence."
)


class SecurityAgent:
    def __init__(
        self,
        llm: LLMClient,
        vector_store: VectorStore,
        tracer: Tracer,
    ) -> None:
        self.llm = llm
        self.vector_store = vector_store
        self.tracer = tracer

    def run(
        self,
        repo_id: str,
        root_path: str,
        files: list[FileRecord],
    ) -> list[Finding]:
        self.tracer.log(
            "security_agent",
            "scan.start",
            repo_id=repo_id,
            files=len(files),
        )

        file_pairs = [(f.path, f.content) for f in files]
        raw_findings = static_analysis.scan(root_path, file_pairs)

        self.tracer.log(
            "security_agent",
            "static_analysis.done",
            count=len(raw_findings),
            tool=(raw_findings[0].source_tool if raw_findings else "none"),
        )

        findings: list[Finding] = []

        for rf in raw_findings:
            context = self.vector_store.query(
                repo_id,
                f"{rf.file} {rf.rule} {rf.message}",
                top_k=3,
            )
            context_text = "\n\n".join(
                c["text"] for c in context[:3]
            )

            snippet = extract_source_snippet(
                           root_path,
                           rf.file,
                           rf.line,
            )
            evidence = snippet or (rf.evidence or "").strip()

            if not evidence:
               evidence = "No source snippet available."

            prompt = (
                f"Rule: {rf.rule}\n"
                f"File: {rf.file}:{rf.line}\n"
                f"Static-analysis message: {rf.message}\n\n"
                f"Evidence:\n{evidence[:400]}\n\n"
                f"Repository context:\n{context_text[:800]}"
            )

            explanation = self.llm.complete(
                prompt,
                system=SYSTEM_PROMPT,
            )

            findings.append(
                make_finding(
                    file=rf.file,
                    line=rf.line,
                    category=Category.SECURITY,
                    rule=rf.rule,
                    title=rf.message,
                    description=explanation,
                    severity=Severity(rf.severity),
                    source_agent="security",
                    source_tool=rf.source_tool,
                    evidence=evidence,
                )
            )

        self.tracer.log(
            "security_agent",
            "scan.done",
            findings=len(findings),
        )

        return findings