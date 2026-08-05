"""Hook logging / execution tracing.

Every agent/tool call in a run is appended as one JSON line to
`logs/<run_id>.jsonl`. This is deliberately a standalone module (not buried
inside the Supervisor) so any agent or tool can log independently — see
prompts.md entry 1.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class Tracer:
    """Thread-safe: Security/Quality/Documentation agents log concurrently
    when the Supervisor runs them in parallel (Week 7 parallel-workers
    scope). A single lock protects both the in-memory event list and the
    JSONL file append so concurrent log() calls can't interleave writes or
    race on the list."""

    def __init__(self, run_id: str, log_dir: Path) -> None:
        self.run_id = run_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"{run_id}.jsonl"
        self._events: list[dict] = []
        self._lock = threading.Lock()

    def log(self, actor: str, event: str, **details: Any) -> None:
        record = {
            "run_id": self.run_id,
            "ts": time.time(),
            "actor": actor,
            "event": event,
            **details,
        }
        with self._lock:
            self._events.append(record)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")

    def events(self) -> list[dict]:
        with self._lock:
            return list(self._events)
