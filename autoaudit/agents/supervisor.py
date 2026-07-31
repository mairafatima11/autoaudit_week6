"""Supervisor Agent: orchestrates the audit run end-to-end — Repository
Agent → Security Agent + Quality Agent → Report Agent — and logs every
step via the Tracer.
"""
from __future__ import annotations

import time
import uuid

from ..config import Config
from ..llm.claude_client import ClaudeClient
from ..llm.gemini_client import GeminiClient
from ..memory.audit_history import AuditHistory
from ..memory.vector_store import VectorStore
from ..schemas import AuditReport
from ..tools.repo_reader import cleanup_if_temp
from ..tracing import Tracer
from .quality_agent import QualityAgent
from .report_agent import ReportAgent
from .repository_agent import RepositoryAgent, repo_id_for
from .security_agent import SecurityAgent
from ..tools.tool_registry import ToolRegistry
from ..tools import repo_reader, static_analysis
from ..tools.embeddings import embed_text


class Supervisor:
    def __init__(self, config: Config) -> None:
        self.config = config

    def run(self, source: str) -> AuditReport:
        run_id = f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        tracer = Tracer(run_id, self.config.log_dir)
        tracer.log("supervisor", "run.start", source=source)
        tool_registry = ToolRegistry()
        tool_registry.register("repo-reader", repo_reader.read_repo)
        tool_registry.register("security-scan", static_analysis.scan)
        tool_registry.register("embeddings", embed_text)
        tracer.log(
            "supervisor",
            "tools.registered",
            tools=tool_registry.list_tools(),
        )

        vector_store = VectorStore(self.config.data_dir / "vector_store.db", dim=self.config.embedding_dim)
        audit_history = AuditHistory(self.config.data_dir / "audit_history.db")

        claude = ClaudeClient(
            api_key=self.config.anthropic_api_key or "",
            model=self.config.anthropic_model,
            mock=not self.config.is_live(),
        )
        gemini = GeminiClient(
            api_key=self.config.gemini_api_key or "",
            model=self.config.gemini_model,
            mock=not self.config.is_live(),
        )

        temp_dir = None
        try:
            repo_agent = RepositoryAgent(vector_store, tracer, max_file_bytes=self.config.max_file_bytes)
            repo_id, files, temp_dir, root_path = repo_agent.build_knowledge_base(source)

            security_agent = SecurityAgent(claude, vector_store, tracer)
            security_findings = security_agent.run(repo_id, str(root_path), files)

            quality_agent = QualityAgent(
                gemini, vector_store, tracer,
                long_function_threshold=self.config.long_function_line_threshold,
            )
            quality_findings = quality_agent.run(repo_id, files)

            report_agent = ReportAgent(audit_history)
            report = report_agent.build_report(
                run_id=run_id,
                repo_id=repo_id,
                repo_source=source,
                findings=security_findings + quality_findings,
                files_scanned=len(files),
                chunks_indexed=vector_store.count(repo_id),
            )

            tracer.log("supervisor", "run.done", findings=len(report.findings))
            return report
        finally:
            vector_store.close()
            audit_history.close()
            cleanup_if_temp(temp_dir)
