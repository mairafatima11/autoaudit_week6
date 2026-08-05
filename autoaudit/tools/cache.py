"""Week 7 performance layer: file-hash based caching so re-audits of an
unchanged repo (or unchanged files within it) skip redundant embedding and
LLM work. Backed by SQLite, consistent with vector_store.py / audit_history.py.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    ts REAL NOT NULL,
    PRIMARY KEY (namespace, key)
);
CREATE TABLE IF NOT EXISTS file_hashes (
    repo_id TEXT NOT NULL,
    file TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    ts REAL NOT NULL,
    PRIMARY KEY (repo_id, file)
);
"""


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()


class Cache:
    """Generic key/value cache (embedding cache, LLM-response cache) plus a
    dedicated file-hash table used for incremental scanning."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ---- generic namespaced cache (embedding cache / LLM cache) --------

    def get(self, namespace: str, key: str):
        cur = self.conn.execute(
            "SELECT value FROM cache_entries WHERE namespace = ? AND key = ?", (namespace, key)
        )
        row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def set(self, namespace: str, key: str, value) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO cache_entries (namespace, key, value, ts) VALUES (?, ?, ?, ?)",
            (namespace, key, json.dumps(value), time.time()),
        )
        self.conn.commit()

    def get_or_compute(self, namespace: str, key: str, compute_fn):
        cached = self.get(namespace, key)
        if cached is not None:
            return cached, True
        value = compute_fn()
        self.set(namespace, key, value)
        return value, False

    # ---- incremental scanning: per-file content hashing -----------------

    def changed_files(self, repo_id: str, files: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
        """Given (path, content) pairs, returns (changed_or_new_paths,
        unchanged_paths) relative to the last recorded hash for this repo."""
        cur = self.conn.execute("SELECT file, content_hash FROM file_hashes WHERE repo_id = ?", (repo_id,))
        known = dict(cur.fetchall())

        changed, unchanged = [], []
        for path, content in files:
            h = hash_content(content)
            if known.get(path) == h:
                unchanged.append(path)
            else:
                changed.append(path)
        return changed, unchanged

    def record_file_hashes(self, repo_id: str, files: list[tuple[str, str]]) -> None:
        now = time.time()
        self.conn.executemany(
            "INSERT OR REPLACE INTO file_hashes (repo_id, file, content_hash, ts) VALUES (?, ?, ?, ?)",
            [(repo_id, path, hash_content(content), now) for path, content in files],
        )
        self.conn.commit()

    def clear_namespace(self, namespace: str) -> None:
        self.conn.execute("DELETE FROM cache_entries WHERE namespace = ?", (namespace,))
        self.conn.commit()
