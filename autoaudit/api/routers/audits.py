from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from ...agents.report_agent import ReportAgent
from ...agents.supervisor import Supervisor
from ...analysis.health_score import compute_health_score
from ...analysis.run_comparison import compare_runs
from ...analysis.test_coverage import signal_from_detail
from ...memory.audit_history import AuditHistory
from ...schemas import AuditReport, FixProposal, RepoHealthScore
from ..dependencies import get_audit_history, get_job_store, get_supervisor
from ..jobs import JobStatus, JobStore
from ..schemas_api import AuditRequest, AuditStartResponse, FixRequest

router = APIRouter(prefix="/api/audits", tags=["audits"])


@router.post("", response_model=AuditStartResponse)
def start_audit(req: AuditRequest, jobs: JobStore = Depends(get_job_store)):
    job = jobs.start(req.source)
    return AuditStartResponse(run_id=job.run_id, status=job.status.value)


_EMPTY_SEVERITY_COUNTS = {"high": 0, "medium": 0, "low": 0, "info": 0}


@router.get("")
def list_audits(
    repo_id: str | None = None,
    jobs: JobStore = Depends(get_job_store),
    history: AuditHistory = Depends(get_audit_history),
):
    """Merges the persisted run history with any in-memory job still in
    flight (which hasn't been saved to audit_history yet).

    Each row now carries the run's health score, finding counts and
    knowledge-base size, so the Memory/Trend views can build every chart
    from this one response instead of fanning out a `GET /api/audits/{id}`
    per run. Pass `repo_id` to scope the history to a single repository —
    trends across mixed repositories aren't trends.
    """
    try:
        persisted = {r["run_id"]: r for r in history.list_runs(repo_id)}
        in_flight_only = [
            {
                "run_id": j.run_id, "repo_id": None, "repo_source": j.source,
                "ts": j.started_at, "status": j.status.value,
                "health_score": None, "files_scanned": None, "chunks_indexed": None,
                "finding_count": 0, "severity_counts": dict(_EMPTY_SEVERITY_COUNTS),
            }
            for j in jobs.list()
            if j.run_id not in persisted
            # An in-flight job has no repo_id yet (it's assigned once the
            # Repository Agent resolves the source), so it can't be matched
            # against a repo filter — omit rather than leak another repo's runs.
            and repo_id is None
        ]
        for r in persisted.values():
            job = jobs.get(r["run_id"])
            r["status"] = job.status.value if job else "done"
    finally:
        history.close()
    combined = list(persisted.values()) + in_flight_only
    combined.sort(key=lambda r: r["ts"], reverse=True)
    return combined


@router.get("/repositories")
def list_repositories(history: AuditHistory = Depends(get_audit_history)):
    """Distinct repositories present in audit history, for the Memory
    page's repository selector."""
    try:
        return {"repositories": history.repositories()}
    finally:
        history.close()


@router.get("/recurring")
def recurring(repo_id: str, min_runs: int = 2, history: AuditHistory = Depends(get_audit_history)):
    """Findings that have appeared in `min_runs` or more runs of one repo."""
    try:
        return {"repo_id": repo_id, "min_runs": min_runs,
                "findings": history.recurring_findings(repo_id, min_runs=min_runs)}
    finally:
        history.close()


@router.get("/compare")
def compare(run_a: str, run_b: str, history: AuditHistory = Depends(get_audit_history)):
    try:
        result = compare_runs(history, run_a, run_b)
    finally:
        history.close()
    return result


@router.get("/{run_id}/status")
def audit_status(run_id: str, jobs: JobStore = Depends(get_job_store)):
    job = jobs.get(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job found for run_id={run_id!r}")
    return jobs.progress(run_id)


@router.get("/{run_id}/events")
def audit_events(run_id: str, jobs: JobStore = Depends(get_job_store)):
    return {"run_id": run_id, "events": jobs.events(run_id)}


def _load_report(run_id: str, jobs: JobStore, history: AuditHistory) -> AuditReport:
    job = jobs.get(run_id)
    if job is not None and job.report is not None:
        return job.report
    if job is not None and job.status == JobStatus.ERROR:
        raise HTTPException(status_code=500, detail=f"Audit run failed: {job.error}")
    if job is not None and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(status_code=202, detail="Audit still running; poll /status")

    # Fall back to persisted history (server restarted, or run predates this process).
    runs = history.list_runs()
    meta = next((r for r in runs if r["run_id"] == run_id), None)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"No audit run found for run_id={run_id!r}")
    findings = history.get_findings_full(run_id)
    # Prefer the counts persisted with the run. Falling back to "number of
    # distinct files that happened to have a finding" badly under-counts a
    # repo (a clean 200-file repo with 3 findings would report 3 files
    # scanned), which then skewed every density in the health score.
    files_scanned = meta.get("files_scanned") or max(len({f.file for f in findings}), 1)
    return AuditReport(
        run_id=run_id,
        repo_id=meta["repo_id"] or "",
        repo_source=meta["repo_source"],
        timestamp=meta["ts"],
        findings=findings,
        files_scanned=files_scanned,
        chunks_indexed=meta.get("chunks_indexed") or 0,
        is_first_run=False,
    )


def _resolve_health_score(report: AuditReport, history: AuditHistory) -> RepoHealthScore:
    """Prefer the health score persisted at the end of the run (computed
    from the real, complete findings + doc_suggestions the job produced)
    over recomputing from `report`.

    `report` here can come from `_load_report`'s history-fallback branch
    (server restarted, or the run predates this process), which only
    reconstructs `findings` from the DB and leaves `doc_suggestions`
    unset — recomputing from that under-counts documentation gaps and
    silently disagrees with what `/api/audits/compare` shows for the same
    run (which already prefers the persisted score; see
    `run_comparison._resolve_health_score`). Falling back to a fresh
    `compute_health_score` only for runs saved before health-score
    persistence existed.
    """
    stored = history.get_health_score(report.run_id)
    if stored is not None:
        return stored
    return compute_health_score(
        report,
        report.doc_suggestions,
        test_signal=signal_from_detail(report.test_coverage),
    )


@router.get("/{run_id}")
def get_audit(run_id: str, jobs: JobStore = Depends(get_job_store), history: AuditHistory = Depends(get_audit_history)):
    try:
        report = _load_report(run_id, jobs, history)
        health = _resolve_health_score(report, history)
        return {"report": report, "health_score": health}
    finally:
        history.close()


@router.get("/{run_id}/report.md", response_class=PlainTextResponse)
def export_markdown(run_id: str, jobs: JobStore = Depends(get_job_store), history: AuditHistory = Depends(get_audit_history)):
    try:
        report = _load_report(run_id, jobs, history)
    finally:
        history.close()
    return ReportAgent.render_markdown(report)


@router.get("/{run_id}/report.json")
def export_json(run_id: str, jobs: JobStore = Depends(get_job_store), history: AuditHistory = Depends(get_audit_history)):
    try:
        report = _load_report(run_id, jobs, history)
        health = _resolve_health_score(report, history)
    finally:
        history.close()
    return {"report": report, "health_score": health}


@router.get("/{run_id}/report.pdf")
def export_pdf(run_id: str, jobs: JobStore = Depends(get_job_store), history: AuditHistory = Depends(get_audit_history)):
    try:
        report = _load_report(run_id, jobs, history)
        health = _resolve_health_score(report, history)
    finally:
        history.close()
    pdf_bytes = ReportAgent.render_pdf(report, health)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="autoaudit-{run_id}.pdf"'},
    )


@router.get("/{run_id}/report.html", response_class=HTMLResponse)
def export_html(run_id: str, jobs: JobStore = Depends(get_job_store), history: AuditHistory = Depends(get_audit_history)):
    try:
        report = _load_report(run_id, jobs, history)
    finally:
        history.close()
    markdown = ReportAgent.render_markdown(report)
    # Minimal, dependency-free MD->HTML so exports don't require a
    # markdown-rendering library; headings/lists/bold render, rest as text.
    import html as html_lib

    lines_html = []
    for line in markdown.splitlines():
        escaped = html_lib.escape(line)
        if line.startswith("### "):
            lines_html.append(f"<h3>{escaped[4:]}</h3>")
        elif line.startswith("## "):
            lines_html.append(f"<h2>{escaped[3:]}</h2>")
        elif line.startswith("# "):
            lines_html.append(f"<h1>{escaped[2:]}</h1>")
        elif line.startswith("- "):
            lines_html.append(f"<li>{escaped[2:]}</li>")
        elif line.strip() == "":
            lines_html.append("<br/>")
        else:
            lines_html.append(f"<p>{escaped}</p>")
    body = "\n".join(lines_html)
    return (
        "<html><head><meta charset='utf-8'><title>AutoAudit AI Report</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;}"
        "h1,h2,h3{color:#111} li{margin-left:1rem}</style></head>"
        f"<body>{body}</body></html>"
    )


@router.post("/{run_id}/fixes", response_model=list[FixProposal])
def propose_fixes(
    run_id: str,
    req: FixRequest,
    jobs: JobStore = Depends(get_job_store),
    history: AuditHistory = Depends(get_audit_history),
    supervisor: Supervisor = Depends(get_supervisor),
):
    try:
        report = _load_report(run_id, jobs, history)
    finally:
        history.close()

    findings = report.findings
    if req.fingerprints:
        wanted = set(req.fingerprints)
        findings = [f for f in findings if f.fingerprint in wanted]
        report = report.model_copy(update={"findings": findings})

    return supervisor.propose_fixes(report, max_findings=req.max_findings)