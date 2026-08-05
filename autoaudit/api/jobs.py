"""In-memory job store + background thread runner for audit runs.

Audits can take a while (LLM calls, embedding, static analysis), so the API
kicks a run off in a background thread and returns immediately with a
run_id the client polls. Live agent-execution status is derived from the
same Tracer JSONL log the CLI already writes — no separate event system
needed, and it works identically whether the run was started via the CLI
or the API.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from ..agents.supervisor import Supervisor
from ..analysis.health_score import compute_health_score
from ..analysis.test_coverage import signal_from_detail
from ..memory.audit_history import AuditHistory
from ..schemas import AuditReport


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class Job:
    run_id: str
    source: str
    status: JobStatus = JobStatus.PENDING
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    report: Optional[AuditReport] = None


# Agent pipeline order used to derive a simple linear progress percentage
# from tracer events, without needing the agents themselves to report
# progress explicitly. The "start" event lets us compute per-stage
# duration; "file_event" is the event name each agent emits while
# processing an individual file, giving the live view a "current file"
# signal without polling agent internals.
PIPELINE_STAGES = [
    ("repository_agent", "read_repo.start", "read_repo.done", None),
    ("security_agent", "scan.start", "scan.done", "processing_file"),
    ("quality_agent", "scan.start", "scan.done", "processing_file"),
    ("documentation_agent", "scan.start", "scan.done", "processing_file"),
    ("supervisor", "run.start", "run.done", None),
]


class JobStore:
    def __init__(self, supervisor: Supervisor, log_dir: Path, audit_history_db_path: Path | None = None) -> None:
        self.supervisor = supervisor
        self.log_dir = Path(log_dir)
        self.audit_history_db_path = audit_history_db_path
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, source: str) -> Job:
        run_id = f"run_{int(time.time())}_{threading.get_ident() % 100000:05d}_{len(self._jobs)}"
        job = Job(run_id=run_id, source=source, status=JobStatus.PENDING)
        with self._lock:
            self._jobs[run_id] = job
        thread = threading.Thread(target=self._execute, args=(job,), daemon=True)
        thread.start()
        return job

    def _execute(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        try:
            report = self.supervisor.run(job.source, run_id=job.run_id)
            job.report = report
            job.status = JobStatus.DONE
            self._persist_health_score(job.run_id, report)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the API caller
            job.error = str(exc)
            job.status = JobStatus.ERROR
        finally:
            job.finished_at = time.time()

    def _persist_health_score(self, run_id: str, report: AuditReport) -> None:
        """Compute and store the health score for this run right away,
        using the real `files_scanned`, `doc_suggestions` and measured test
        signal that are only available here (right after the full pipeline
        finishes). Run Comparison reads this back later instead of
        recomputing from reconstructed findings alone, which — lacking these
        inputs — produced a different (and often unchanged-looking) score
        than what was shown when each run completed."""
        if self.audit_history_db_path is None:
            return
        # SQLite connections aren't thread-safe to share; open one scoped
        # to this background thread rather than reusing a request-scoped one.
        history = AuditHistory(self.audit_history_db_path)
        try:
            health = compute_health_score(
                report,
                report.doc_suggestions,
                files_scanned=report.files_scanned,
                test_signal=signal_from_detail(report.test_coverage),
            )
            history.save_health_score(run_id, health)
        finally:
            history.close()

    def get(self, run_id: str) -> Optional[Job]:
        return self._jobs.get(run_id)

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)

    def events(self, run_id: str) -> list[dict]:
        """Read the Tracer's JSONL log for this run. Safe to call while the
        run is still in progress — it just reads whatever's been flushed."""
        path = self.log_dir / f"{run_id}.jsonl"
        if not path.exists():
            return []
        events = []
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def progress(self, run_id: str) -> dict:
        """Derive a per-agent progress view (status, duration, current
        file, error) from tracer events for the Live Agent Execution
        Visualization — no separate progress-reporting system needed since
        every agent already calls the same Tracer."""
        events = self.events(run_id)
        by_actor_event: dict[tuple[str, str], dict] = {}
        last_file_by_actor: dict[str, tuple[float, str]] = {}
        for e in events:
            key = (e.get("actor"), e.get("event"))
            by_actor_event[key] = e
            if e.get("event") == "processing_file" and "file" in e:
                actor = e.get("actor")
                ts = e.get("ts", 0)
                if actor not in last_file_by_actor or ts > last_file_by_actor[actor][0]:
                    last_file_by_actor[actor] = (ts, e["file"])

        job = self.get(run_id)
        stages = []
        completed_count = 0
        now = time.time()

        for actor, start_event, done_event, file_event in PIPELINE_STAGES:
            start_rec = by_actor_event.get((actor, start_event))
            done_rec = by_actor_event.get((actor, done_event))
            is_done = done_rec is not None
            completed_count += 1 if is_done else 0

            duration_seconds = None
            if start_rec:
                end_ts = done_rec["ts"] if done_rec else now
                duration_seconds = round(end_ts - start_rec["ts"], 2)

            stage = {
                "agent": actor,
                "status": "completed" if is_done else "pending",
                "duration_seconds": duration_seconds,
                "current_file": last_file_by_actor.get(actor, (None, None))[1] if not is_done else None,
            }
            stages.append(stage)

        if job and job.status == JobStatus.RUNNING:
            for stage in stages:
                if stage["status"] == "pending":
                    stage["status"] = "running"
                    break
        elif job and job.status == JobStatus.ERROR:
            for stage in stages:
                if stage["status"] == "pending":
                    stage["status"] = "error"
                    break

        percent = round(100 * completed_count / len(PIPELINE_STAGES))
        return {
            "run_id": run_id,
            "status": job.status.value if job else "unknown",
            "percent": percent,
            "stages": stages,
            "error": job.error if job else None,
        }
