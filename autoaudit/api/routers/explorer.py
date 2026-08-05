"""Interactive Repository Explorer API: serves the file tree and individual
file contents for a completed run, with that file's findings attached so
the frontend can highlight the exact lines without a second round trip.

Files are served from the Supervisor's in-memory run context (the same
FileRecord list the Repository Agent built), not from disk — this works
uniformly whether the run was a local path or a cloned git repo whose temp
directory has since been deleted.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...agents.supervisor import Supervisor
from ..dependencies import get_audit_history, get_job_store, get_supervisor
from ..jobs import JobStore
from ..routers.audits import _load_report
from ...memory.audit_history import AuditHistory

router = APIRouter(prefix="/api/audits", tags=["explorer"])


def _tree_from_paths(paths: list[str]) -> dict:
    """Build a nested {name, type, path, children} tree from a flat list of
    relative file paths. Directories are synthesized from path segments."""
    root: dict = {"name": "", "type": "dir", "path": "", "children": {}}
    for p in paths:
        parts = p.split("/")
        node = root
        for i, part in enumerate(parts):
            is_file = i == len(parts) - 1
            key = part
            if key not in node["children"]:
                node["children"][key] = {
                    "name": part,
                    "type": "file" if is_file else "dir",
                    "path": "/".join(parts[: i + 1]),
                    "children": {},
                }
            node = node["children"][key]

    def serialize(node: dict) -> dict:
        children = sorted(node["children"].values(), key=lambda n: (n["type"] != "dir", n["name"].lower()))
        result = {"name": node["name"], "type": node["type"], "path": node["path"]}
        if node["type"] == "dir":
            result["children"] = [serialize(c) for c in children]
        return result

    return serialize(root)


@router.get("/{run_id}/files")
def get_file_tree(
    run_id: str,
    supervisor: Supervisor = Depends(get_supervisor),
    jobs: JobStore = Depends(get_job_store),
):
    files = supervisor.get_files(run_id)
    if files is None:
        job = jobs.get(run_id)
        if job is not None:
            raise HTTPException(
                status_code=404,
                detail="File contents for this run aren't held in memory anymore (server may have restarted).",
            )
        raise HTTPException(status_code=404, detail=f"No run found for run_id={run_id!r}")

    paths = [f.path for f in files]
    return {"run_id": run_id, "tree": _tree_from_paths(paths), "file_count": len(paths)}


@router.get("/{run_id}/file")
def get_file_content(
    run_id: str,
    path: str,
    supervisor: Supervisor = Depends(get_supervisor),
    jobs: JobStore = Depends(get_job_store),
    history: AuditHistory = Depends(get_audit_history),
):
    files = supervisor.get_files(run_id)
    if files is None:
        raise HTTPException(
            status_code=404,
            detail="File contents for this run aren't held in memory anymore (server may have restarted).",
        )
    record = next((f for f in files if f.path == path), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No file at path={path!r} in run {run_id!r}")

    try:
        report = _load_report(run_id, jobs, history)
    finally:
        history.close()

    file_findings = [
        {
            "fingerprint": f.fingerprint,
            "line": f.line,
            "severity": f.severity,
            "title": f.title,
            "rule": f.rule,
            "source_agent": f.source_agent,
            "confidence": f.confidence,
        }
        for f in report.findings
        if f.file == path
    ]

    return {
        "run_id": run_id,
        "path": record.path,
        "language": record.language,
        "content": record.content,
        "findings": file_findings,
    }
