from __future__ import annotations


from autoaudit.agents.fix_agent import FixAgent
from autoaudit.agents.documentation_agent import DocumentationAgent
from autoaudit.agents.reconciliation import ReconciliationEngine
from autoaudit.agents.repository_agent import RepositoryAgent
from autoaudit.analysis.health_score import compute_health_score
from autoaudit.llm.gemini_client import GeminiClient
from autoaudit.llm.groq_client import GroqClient
from autoaudit.llm.router import ModelRouter, RouterConfig
from autoaudit.llm.validation import ValidationFailure, validate_with_repair
from autoaudit.memory.vector_store import VectorStore
from autoaudit.schemas import (
    AuditReport,
    Category,
    FixProposal,
    Severity,
    make_finding,
)
from autoaudit.tools.cache import Cache
from autoaudit.tracing import Tracer


def _finding(file="src/app.py", line=3, category=Category.SECURITY, rule="hardcoded-secret",
             severity=Severity.HIGH, source_agent="security"):
    return make_finding(
        file=file, line=line, category=category, rule=rule,
        title=f"{rule} issue", description="desc", severity=severity,
        source_agent=source_agent, source_tool="test",
    )


# ---- ModelRouter -----------------------------------------------------------

def test_router_completes_with_preferred_provider():
    router = ModelRouter({"groq": GroqClient(mock=True), "gemini": GeminiClient(mock=True)})
    result = router.complete("explain this eval() call", profile="precision")
    assert result.error is None
    assert result.provider == "groq"
    assert result.response.startswith("[mock-groq]")


def test_router_falls_back_when_preferred_provider_missing():
    router = ModelRouter({"gemini": GeminiClient(mock=True)})
    result = router.complete("test", profile="precision")
    assert result.error is None
    assert result.provider == "gemini"


def test_router_compare_runs_all_providers():
    router = ModelRouter({"groq": GroqClient(mock=True), "gemini": GeminiClient(mock=True)})
    comparison = router.compare("summarize this function")
    providers = {r.provider for r in comparison.results}
    assert providers == {"groq", "gemini"}
    assert comparison.merged_answer


def test_router_retries_and_reports_error_on_persistent_failure():
    class BrokenClient:
        provider = "broken"
        model = "x"

        def complete(self, prompt, system=None):
            raise RuntimeError("boom")

    router = ModelRouter({"broken": BrokenClient()}, config=RouterConfig(max_retries=1, retry_backoff_seconds=0))
    result = router.complete("test", provider="broken")
    assert result.error is not None
    assert "boom" in result.error


# ---- validation -------------------------------------------------------------

def test_validate_with_repair_accepts_valid_json_first_try():
    raw = (
        '{"finding_fingerprint": "abc", "file": "a.py", "patch": "diff", '
        '"pr_title": "t", "pr_description": "d", "commit_message": "c", '
        '"suggested_unit_test": "u", "suggested_integration_test": "i", '
        '"estimated_impact": "low", "estimated_confidence": 0.5}'
    )
    result = validate_with_repair(FixProposal, raw, primary_client=GeminiClient(mock=True))
    assert isinstance(result.value, FixProposal)
    assert result.attempts == 1
    assert not result.repaired


def test_validate_with_repair_raises_after_exhausting_attempts():
    class AlwaysBadClient:
        provider = "bad"

        def complete(self, prompt, system=None):
            return "not json at all"

    try:
        validate_with_repair(
            FixProposal, "still not json", primary_client=AlwaysBadClient(),
            max_repair_attempts=1,
        )
        assert False, "expected ValidationFailure"
    except ValidationFailure as exc:
        assert exc.schema is FixProposal
        assert len(exc.attempts) >= 1


# ---- Fix Agent ---------------------------------------------------------------

def test_fix_agent_mock_mode_produces_valid_proposal(tmp_path):
    router = ModelRouter({"groq": GroqClient(mock=True), "gemini": GeminiClient(mock=True)})
    tracer = Tracer("test_fix_run", tmp_path / "logs")
    agent = FixAgent(router, tracer, root_path="tests/fixtures/mock_repo")
    finding = _finding()
    proposal = agent.propose_fix(finding)
    assert isinstance(proposal, FixProposal)
    assert proposal.finding_fingerprint == finding.fingerprint
    assert proposal.file == finding.file
    assert "---" in proposal.patch and "+++" in proposal.patch
    assert 0.0 <= proposal.estimated_confidence <= 1.0


def test_fix_agent_never_writes_to_disk(tmp_path):
    """Sanity check: FixAgent has no filesystem-write API surface at all."""
    assert not hasattr(FixAgent, "apply")
    assert not hasattr(FixAgent, "write")
    assert not hasattr(FixAgent, "commit")


# ---- Documentation Agent -----------------------------------------------------

def test_documentation_agent_finds_missing_docstrings_and_readme_gaps(tmp_path):
    tracer = Tracer("test_doc_run", tmp_path / "logs")
    store = VectorStore(tmp_path / "vs.db")
    repo_agent = RepositoryAgent(store, tracer)
    repo_id, files, temp_dir, root = repo_agent.build_knowledge_base("tests/fixtures/mock_repo")

    router = ModelRouter({"groq": GroqClient(mock=True), "gemini": GeminiClient(mock=True)})
    doc_agent = DocumentationAgent(router, tracer)
    suggestions = doc_agent.run(files, readme_text="# My Project\nJust a description.")

    kinds = {s.kind for s in suggestions}
    assert "missing_docstring" in kinds
    assert "missing_readme_section" in kinds
    assert all(s.suggestion for s in suggestions)
    store.close()


def test_documentation_agent_generates_architecture_explanation(tmp_path):
    tracer = Tracer("test_doc_arch_run", tmp_path / "logs")
    store = VectorStore(tmp_path / "vs.db")
    repo_agent = RepositoryAgent(store, tracer)
    repo_id, files, temp_dir, root = repo_agent.build_knowledge_base("tests/fixtures/mock_repo")

    router = ModelRouter({"groq": GroqClient(mock=True), "gemini": GeminiClient(mock=True)})
    doc_agent = DocumentationAgent(router, tracer)
    explanation = doc_agent.generate_architecture_explanation(files)

    assert isinstance(explanation, str)
    assert len(explanation) > 0
    assert str(len(files)) in explanation  # grounded in the real file count, not invented
    store.close()


def test_architecture_explanation_empty_for_no_files(tmp_path):
    tracer = Tracer("test_doc_empty_run", tmp_path / "logs")
    router = ModelRouter({"groq": GroqClient(mock=True), "gemini": GeminiClient(mock=True)})
    doc_agent = DocumentationAgent(router, tracer)
    explanation = doc_agent.generate_architecture_explanation([])
    assert "No files" in explanation


# ---- Reconciliation -----------------------------------------------------------

def test_reconciliation_groups_overlapping_findings_from_multiple_agents():
    findings = [
        _finding(line=10, source_agent="security", severity=Severity.HIGH, rule="sql-injection"),
        _finding(line=11, source_agent="quality", severity=Severity.MEDIUM, rule="long-function", category=Category.QUALITY),
        _finding(line=200, source_agent="quality", severity=Severity.LOW, rule="duplicate-code", category=Category.QUALITY),
    ]
    engine = ReconciliationEngine(line_window=3)
    reconciled = engine.reconcile(findings)

    assert len(reconciled) == 2  # (10,11) grouped, (200) alone
    overlapping = next(r for r in reconciled if r.line in (10, 11))
    assert overlapping.agreement is True
    assert set(overlapping.contributing_agents) == {"security", "quality"}
    assert overlapping.conflict is not None  # severities differ (high vs medium)

    solo = next(r for r in reconciled if r.line == 200)
    assert solo.agreement is False


def test_reconciliation_priority_ordering_puts_high_severity_agreement_first():
    findings = [
        _finding(line=1, source_agent="security", severity=Severity.HIGH, rule="secret"),
        _finding(line=2, source_agent="quality", severity=Severity.HIGH, rule="secret", category=Category.QUALITY),
        _finding(line=500, source_agent="quality", severity=Severity.INFO, rule="missing-docstring", category=Category.QUALITY),
    ]
    engine = ReconciliationEngine(line_window=3)
    reconciled = engine.reconcile(findings)
    assert reconciled[0].priority <= reconciled[-1].priority


def test_reconciliation_confidence_by_fingerprint_covers_all_group_members():
    findings = [
        _finding(line=10, source_agent="security", severity=Severity.HIGH, rule="sql-injection"),
        _finding(line=11, source_agent="quality", severity=Severity.MEDIUM, rule="long-function", category=Category.QUALITY),
        _finding(line=200, source_agent="quality", severity=Severity.LOW, rule="duplicate-code", category=Category.QUALITY),
    ]
    engine = ReconciliationEngine(line_window=3)
    conf_map = engine.confidence_by_fingerprint(findings)
    assert len(conf_map) == 3
    # The two overlapping (agreeing) findings should share the same confidence.
    assert conf_map[findings[0].fingerprint] == conf_map[findings[1].fingerprint]
    # The solo finding should have a different (lower) confidence than the agreeing pair.
    assert conf_map[findings[2].fingerprint] != conf_map[findings[0].fingerprint]
    assert all(0.0 <= v <= 1.0 for v in conf_map.values())


def test_supervisor_runs_security_quality_documentation_agents_in_parallel(tmp_path):
    """Confirms real concurrency (not just that parallel code exists): each
    agent's scan.start event should land within a small window of the
    others', rather than being spaced out sequentially."""
    from autoaudit.config import Config
    from autoaudit.agents.supervisor import Supervisor

    cfg = Config(mode="mock", data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    sup = Supervisor(cfg)
    report = sup.run("tests/fixtures/mock_repo")

    events = sup._run_contexts  # noqa: SLF001 - test-only introspection
    log_path = cfg.log_dir / f"{report.run_id}.jsonl"
    import json as _json
    starts = {}
    for line in log_path.read_text().splitlines():
        rec = _json.loads(line)
        if rec["event"] == "scan.start" and rec["actor"] in ("security_agent", "quality_agent", "documentation_agent"):
            starts[rec["actor"]] = rec["ts"]

    assert set(starts.keys()) == {"security_agent", "quality_agent", "documentation_agent"}
    spread = max(starts.values()) - min(starts.values())
    # Sequential execution of 3 agents doing real work would take much
    # longer than this; a tight spread is evidence they were dispatched
    # concurrently rather than one after another.
    assert spread < 0.5


# ---- Health score ---------------------------------------------------------------

def test_health_score_penalizes_high_severity_security_findings():
    clean_report = AuditReport(run_id="r1", repo_id="x", repo_source="s", files_scanned=5)
    dirty_report = AuditReport(
        run_id="r2", repo_id="x", repo_source="s", files_scanned=5,
        findings=[_finding(severity=Severity.HIGH) for _ in range(3)],
    )
    clean_score = compute_health_score(clean_report)
    dirty_score = compute_health_score(dirty_report)
    assert clean_score.security == 100
    assert dirty_score.security < clean_score.security
    assert 0 <= dirty_score.overall <= 100


# ---- Cache / incremental scanning ------------------------------------------------

def test_cache_changed_files_detects_new_and_unchanged(tmp_path):
    cache = Cache(tmp_path / "cache.db")
    files_v1 = [("a.py", "print(1)"), ("b.py", "print(2)")]
    changed, unchanged = cache.changed_files("repo1", files_v1)
    assert set(changed) == {"a.py", "b.py"}
    assert unchanged == []

    cache.record_file_hashes("repo1", files_v1)
    files_v2 = [("a.py", "print(1)"), ("b.py", "print(999)")]  # only b.py changed
    changed2, unchanged2 = cache.changed_files("repo1", files_v2)
    assert changed2 == ["b.py"]
    assert unchanged2 == ["a.py"]
    cache.close()


def test_cache_get_or_compute_reuses_value(tmp_path):
    cache = Cache(tmp_path / "cache.db")
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return [1, 2, 3]

    v1, hit1 = cache.get_or_compute("embeddings", "key1", compute)
    v2, hit2 = cache.get_or_compute("embeddings", "key1", compute)
    assert v1 == v2 == [1, 2, 3]
    assert hit1 is False
    assert hit2 is True
    assert calls["n"] == 1
    cache.close()
