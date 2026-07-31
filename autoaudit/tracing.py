"""Hook logging / execution tracing.

Every agent/tool call in a run is appended as one JSON line to
`logs/<run_id>.jsonl`. This is deliberately a standalone module (not buried
inside the Supervisor) so any agent or tool can log independently — see
prompts.md entry 1.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class Tracer:
    def __init__(self, run_id: str, log_dir: Path) -> None:
        self.run_id = run_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"{run_id}.jsonl"
        self._events: list[dict] = []

    def log(self, actor: str, event: str, **details: Any) -> None:
        record = {
            "run_id": self.run_id,
            "ts": time.time(),
            "actor": actor,
            "event": event,
            **details,
        }
        self._events.append(record)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    def events(self) -> list[dict]:
        return list(self._events)
