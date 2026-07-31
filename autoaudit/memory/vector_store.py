"""Repository Knowledge Base: a SQLite-backed vector store for per-file/
function embeddings, per the proposal's "vector store (e.g. Chroma or
SQLite plus embeddings)" tech choice. Cosine similarity search is done in
Python/numpy — fine at the scale of a single repo's chunks, and keeps the
project dependency-light and fully offline-runnable.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from ..tools.embeddings import cosine_similarity, embed_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    file TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    text TEXT NOT NULL,
    vector TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_repo ON chunks(repo_id);
"""


class VectorStore:
    def __init__(self, db_path: Path, dim: int = 256) -> None:
        self.db_path = Path(db_path)
        self.dim = dim
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

    def clear_repo(self, repo_id: str) -> None:
        self.conn.execute("DELETE FROM chunks WHERE repo_id = ?", (repo_id,))
        self.conn.commit()

    def add_chunk(self, repo_id: str, chunk_id: str, file: str, start_line: int, text: str) -> None:
        vec = embed_text(text, dim=self.dim)
        self.conn.execute(
            "INSERT OR REPLACE INTO chunks (id, repo_id, file, start_line, text, vector) VALUES (?, ?, ?, ?, ?, ?)",
            (f"{repo_id}::{chunk_id}", repo_id, file, start_line, text, json.dumps(vec.tolist())),
        )

    def commit(self) -> None:
        self.conn.commit()

    def count(self, repo_id: str) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM chunks WHERE repo_id = ?", (repo_id,))
        return int(cur.fetchone()[0])

    def query(self, repo_id: str, query_text: str, top_k: int = 5) -> list[dict]:
        if not query_text.strip():
            return []
        q_vec = embed_text(query_text, dim=self.dim)
        cur = self.conn.execute(
            "SELECT id, file, start_line, text, vector FROM chunks WHERE repo_id = ?", (repo_id,)
        )
        rows = cur.fetchall()
        scored = []
        for _id, file, start_line, text, vector_json in rows:
            vec = np.array(json.loads(vector_json), dtype=np.float32)
            score = cosine_similarity(q_vec, vec)
            scored.append({"file": file, "start_line": start_line, "text": text, "score": score})
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:top_k]

    def similar_chunks(self, repo_id: str, min_score: float = 0.92) -> list[tuple[dict, dict]]:
        """Find near-duplicate chunk pairs (used by the Quality Agent to
        flag possible duplicated code)."""
        cur = self.conn.execute(
            "SELECT id, file, start_line, text, vector FROM chunks WHERE repo_id = ?", (repo_id,)
        )
        rows = [
            {"id": r[0], "file": r[1], "start_line": r[2], "text": r[3],
             "vector": np.array(json.loads(r[4]), dtype=np.float32)}
            for r in cur.fetchall()
        ]
        pairs = []
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                if a["file"] == b["file"] and a["start_line"] == b["start_line"]:
                    continue
                if len(a["text"]) < 60 or len(b["text"]) < 60:
                    continue  
                score = cosine_similarity(a["vector"], b["vector"])
                if score >= min_score:
                    pairs.append((a, b))
        return pairs
