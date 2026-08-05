"""Process-wide singletons for the API layer. A single Supervisor instance
is shared across requests so its `_run_contexts` map (used by
`propose_fixes` to reuse an in-flight run's router/root_path) actually
works across the lifetime of the server process.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from ..agents.supervisor import Supervisor
from ..config import Config, load_config
from ..memory.audit_history import AuditHistory
from .jobs import JobStore


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()


@lru_cache(maxsize=1)
def get_supervisor() -> Supervisor:
    return Supervisor(get_config())


@lru_cache(maxsize=1)
def get_job_store() -> JobStore:
    config = get_config()
    return JobStore(get_supervisor(), config.log_dir, config.data_dir / "audit_history.db")


def get_audit_history(config: Config = Depends(get_config)) -> AuditHistory:
    """A fresh connection per request — SQLite connections aren't safe to
    share across threads, and FastAPI may serve requests on different
    threadpool threads.

    `config` is injected rather than fetched by calling `get_config()`
    directly: a direct call bypasses FastAPI's `dependency_overrides`, so
    tests that override the config to point at a tmp directory were still
    opening (and writing to) the real `./data/audit_history.db`.
    """
    return AuditHistory(config.data_dir / "audit_history.db")
