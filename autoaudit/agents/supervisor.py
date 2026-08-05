"""Supervisor Agent: orchestrates the audit run end-to-end — Repository
Agent → (Security Agent + Quality Agent + Documentation Agent, run in
parallel — they're independent of each other) → Reconciliation → Report
Agent — and logs every step via the Tracer. Fix Agent proposals are
generated on demand (via `propose_fixes`) rather than on every run, since
they're comparatively expensive and only needed once findings exist.

Provider selection for every agent goes through `ProviderRegistry`
(`llm/registry.py`) rather than constructing GroqClient/GeminiClient
inline — see that module's docstring for why.
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import time
import uuid

from ..analysis.test_coverage import analyze_test_coverage
from ..config import Config
from ..llm.registry import ProviderRegistry
from ..llm.router import ModelRouter
from ..memory.audit_history import AuditHistory
from ..memory.vector_store import VectorStore
from ..schemas import (
    AuditReport,
    RepoProfile as RepoProfileSchema,
    TestCoverageDetail,
)
from ..tools.cache import Cache
from ..tools.repo_reader import cleanup_if_temp
from ..tracing import Tracer
from .documentation_agent import DocumentationAgent
from .fix_agent import FixAgent
from .quality_agent import QualityAgent
from .reconciliation import ReconciliationEngine
from .report_agent import ReportAgent
from .repository_agent import RepositoryAgent
from .security_agent import SecurityAgent
from ..tools.tool_registry import ToolRegistry
from ..tools import repo_reader, static_analysis
from ..tools.embeddings import embed_text
from ..tools.repo_profiler import profile_repository


class Supervisor:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._run_contexts: dict[str, dict] = {}

    def run(self, source: str, run_id: str | None = None) -> AuditReport:
        run_id = run_id or f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
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
        cache = Cache(self.config.data_dir / "cache.db")

        registry = ProviderRegistry(self.config)
        router = ModelRouter(registry.get_all())

        temp_dir = None
        try:
            repo_agent = RepositoryAgent(
                vector_store, tracer, max_file_bytes=self.config.max_file_bytes, cache=cache
            )
            repo_id, files, temp_dir, root_path = repo_agent.build_knowledge_base(source)

            security_agent = SecurityAgent(
                registry.for_agent("security"), vector_store, tracer,
                router=router, provider=self.config.security_agent_provider,
                batch_size=self.config.security_agent_batch_size,
            )
            quality_agent = QualityAgent(
                registry.for_agent("quality"), vector_store, tracer,
                long_function_threshold=self.config.long_function_line_threshold,
                batch_size=self.config.quality_agent_batch_size,
                duplicate_min_score=self.config.quality_duplicate_min_score,
                # Routed so a provider outage (e.g. Gemini 503 "high
                # demand") fails over to the secondary provider instead of
                # ending the run — batching/spacing only ever addressed 429.
                router=router,
                provider=self.config.quality_agent_provider,
            )
            doc_agent = DocumentationAgent(
                router, tracer, provider=self.config.documentation_agent_provider,
                batch_size=self.config.documentation_agent_batch_size,
                include_tests=self.config.documentation_include_tests,
                skip_generated_migrations=self.config.documentation_skip_generated_migrations,
            )
            readme_path = None
            for candidate in ("README.md", "readme.md", "Readme.md"):
                if (root_path / candidate).exists():
                    readme_path = root_path / candidate
                    break
            readme_text = readme_path.read_text(encoding="utf-8", errors="ignore") if readme_path else ""

            # Security's run() and Quality/Documentation's detect() don't
            # depend on each other's output — only on the Repository
            # Agent's output above — so they run concurrently.
            # VectorStore and Tracer are both internally locked for
            # exactly this (see their docstrings); each agent still uses
            # its own LLM client instance, so there's no shared mutable
            # LLM state either.
            #
            # Quality.draft() and Documentation.draft() are each other's
            # only remaining dependency-free-but-Gemini-bound step, so
            # running them concurrently reintroduces the exact 429 burst
            # this split was meant to avoid. They're run sequentially
            # afterwards instead — Quality first, then Documentation.
            # Detection only — all three passes are deterministic (static
            # analysis, heuristics, vector similarity) with no network cost,
            # so the parallel phase now finishes in seconds. Security's
            # model calls used to sit inside this block, which meant Quality
            # and Documentation detection completed early and then waited on
            # it: on a repo where Semgrep returns hundreds of findings the
            # whole pipeline stalled here for minutes, and the live view
            # showed everything queued behind a spinning Security stage.
            tracer.log(
                "supervisor", "parallel_agents.start",
                agents=["security.detect", "quality.detect", "documentation.detect"],
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                security_pending_future = pool.submit(security_agent.detect, repo_id, str(root_path), files)
                quality_pending_future = pool.submit(quality_agent.detect, repo_id, files)
                doc_pending_future = pool.submit(doc_agent.detect, files, readme_text=readme_text)

                security_pending = security_pending_future.result()
                quality_pending = quality_pending_future.result()
                doc_pending = doc_pending_future.result()
            tracer.log("supervisor", "parallel_agents.done")

            # Drafting is the model-bound phase. Kept sequential so the two
            # Gemini-backed agents don't burst the same key at once (the
            # original reason for this split). Security goes first: it's on
            # a different provider and its findings are the highest-value
            # output, so they land as early as possible.
            tracer.log("supervisor", "draft_agents.start", agents=["security", "quality", "documentation"])
            security_findings = security_agent.draft(security_pending)
            quality_findings = quality_agent.draft(quality_pending)
            doc_suggestions = doc_agent.draft(doc_pending)
            degraded = (
                security_agent.degraded_count
                + quality_agent.degraded_count
                + doc_agent.degraded_count
            )
            tracer.log(
                "supervisor", "draft_agents.done",
                degraded_security=security_agent.degraded_count,
                degraded_quality=quality_agent.degraded_count,
                degraded_documentation=doc_agent.degraded_count,
            )

            tracer.log("supervisor", "architecture_explanation.start")
            architecture_explanation = doc_agent.generate_architecture_explanation(files)
            tracer.log("supervisor", "architecture_explanation.done")

            all_findings = security_findings + quality_findings
            reconciler = ReconciliationEngine()
            reconciled = reconciler.reconcile(all_findings)
            confidence_map = reconciler.confidence_by_fingerprint(all_findings)
            for f in all_findings:
                f.confidence = confidence_map.get(f.fingerprint, f.confidence)

            report_agent = ReportAgent(audit_history)
            report = report_agent.build_report(
                run_id=run_id,
                repo_id=repo_id,
                repo_source=source,
                findings=all_findings,
                files_scanned=len(files),
                chunks_indexed=vector_store.count(repo_id),
            )

            tracer.log(
                "supervisor", "run.done",
                findings=len(report.findings),
                doc_suggestions=len(doc_suggestions),
                reconciled_groups=len(reconciled),
            )
            report.doc_suggestions = doc_suggestions
            report.reconciled_findings = reconciled
            report.architecture_explanation = architecture_explanation
            report.repo_profile = RepoProfileSchema(**dataclasses.asdict(profile_repository(files)))

            # Real test signal measured from the repo's own files, replacing
            # the constant that used to be hardcoded into the health score.
            signal = analyze_test_coverage(files)
            report.test_coverage = TestCoverageDetail(
                measured=signal.measured,
                score=signal.score,
                source_files=signal.source_files,
                test_files=signal.test_files,
                test_cases=signal.test_cases,
                source_symbols=signal.source_symbols,
                modules_with_tests=signal.modules_with_tests,
                module_coverage_pct=signal.module_coverage_pct,
            )
            tracer.log(
                "supervisor", "test_coverage.measured",
                score=signal.score, test_files=signal.test_files,
                test_cases=signal.test_cases, measured=signal.measured,
            )

            # A run that completed with some model-authored text missing is
            # still a useful run — but the user must be told, rather than
            # silently shown placeholder prose next to real findings.
            report.degraded_suggestions = degraded

            self._run_contexts[run_id] = {"root_path": str(root_path), "router": router, "files": files}
            return report
        finally:
            vector_store.close()
            audit_history.close()
            cache.close()
            cleanup_if_temp(temp_dir)

    def get_files(self, run_id: str):
        """Return this run's FileRecord list from the in-memory context, or
        None if the run predates this process (server restart) or was
        never held in memory. Powers the Interactive Repository Explorer —
        kept in memory rather than re-read from disk since cloned repos'
        temp directories are deleted once the run finishes."""
        context = self._run_contexts.get(run_id)
        return context.get("files") if context else None

    def propose_fixes(
        self, report: AuditReport, max_findings: int | None = 10
    ) -> list:
        """Run the Fix Agent over a completed report's findings. Kept
        separate from `run()` since fix proposals are expensive and are
        typically requested for a subset of findings from the UI."""
        context = self._run_contexts.get(report.run_id, {})
        router = context.get("router")
        root_path = context.get("root_path", "")
        # `files` still holds each FileRecord's full content in memory —
        # the same data the Explorer already relies on for cloned repos
        # whose temp directory is long gone by the time this is called.
        # Passing it to FixAgent lets it read real source via
        # extract_source_snippet_from_content instead of trying (and
        # silently failing) to re-read root_path from disk, which is what
        # was producing ungrounded/hallucinated patches for URL-sourced
        # repos like a GitHub-cloned Flask.
        files = context.get("files")
        if router is None:
            registry = ProviderRegistry(self.config)
            router = ModelRouter(registry.get_all())

        tracer = Tracer(f"{report.run_id}_fixes", self.config.log_dir)
        fix_agent = FixAgent(
            router, tracer, root_path=root_path, files=files,  # noqa: E501 - see FixAgent.__init__
            primary_provider=self.config.fix_agent_provider,
            fallback_provider="gemini" if self.config.fix_agent_provider != "gemini" else "groq",
        )
        return fix_agent.propose_fixes(report.findings, max_findings=max_findings)