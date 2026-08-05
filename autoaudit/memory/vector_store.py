"""Repository Knowledge Base: a SQLite-backed vector store for per-file/
function embeddings, per the proposal's "vector store (e.g. Chroma or
SQLite plus embeddings)" tech choice. Cosine similarity search is done in
Python/numpy — fine at the scale of a single repo's chunks, and keeps the
project dependency-light and fully offline-runnable.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import numpy as np

from ..tools.embeddings import cosine_similarity, embed_text, embed_texts_batch, keyword_overlap_score

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
    """Thread-safe: `check_same_thread=False` plus an internal lock around
    every DB access, since the Supervisor runs Security/Quality/Documentation
    agents concurrently against one VectorStore instance (Week 7 parallel-
    workers scope) — the stdlib sqlite3 module doesn't guarantee safety for
    concurrent use of one connection across threads on its own."""

    def __init__(self, db_path: Path, dim: int = 256) -> None:
        self.db_path = Path(db_path)
        self.dim = dim
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def clear_repo(self, repo_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM chunks WHERE repo_id = ?", (repo_id,))
            self.conn.commit()

    def delete_file(self, repo_id: str, file: str) -> None:
        """Remove just one file's chunks — used for incremental re-indexing
        so unchanged files' embeddings/chunks are left untouched."""
        with self._lock:
            self.conn.execute("DELETE FROM chunks WHERE repo_id = ? AND file = ?", (repo_id, file))
            self.conn.commit()

    def add_chunk(self, repo_id: str, chunk_id: str, file: str, start_line: int, text: str, cache=None) -> None:
        if cache is not None:
            from ..tools.cache import hash_content

            key = hash_content(text)
            cached_vec, _hit = cache.get_or_compute(
                "embeddings", key, lambda: embed_text(text, dim=self.dim).tolist()
            )
            vec_list = cached_vec
        else:
            vec_list = embed_text(text, dim=self.dim).tolist()
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO chunks (id, repo_id, file, start_line, text, vector) VALUES (?, ?, ?, ?, ?, ?)",
                (f"{repo_id}::{chunk_id}", repo_id, file, start_line, text, json.dumps(vec_list)),
            )

    def add_chunks_batch(self, repo_id: str, chunks: list[dict], cache=None) -> None:
        """Batch-insert many chunks at once. Each dict needs id/file/
        start_line/text. Embeds every chunk not already in the cache in a
        single `embed_texts_batch` call, then does one `executemany` for
        the SQLite insert — versus one embed call + one INSERT per chunk
        via `add_chunk`. This is what `RepositoryAgent` uses for a repo's
        changed files instead of looping over `add_chunk`."""
        if not chunks:
            return

        if cache is not None:
            from ..tools.cache import hash_content

            keys = [hash_content(c["text"]) for c in chunks]
            to_embed_idx = [i for i, k in enumerate(keys) if cache.get("embeddings", k) is None]
            if to_embed_idx:
                fresh_vecs = embed_texts_batch([chunks[i]["text"] for i in to_embed_idx], dim=self.dim)
                for pos, i in enumerate(to_embed_idx):
                    cache.set("embeddings", keys[i], fresh_vecs[pos].tolist())
            vectors = [cache.get("embeddings", k) for k in keys]
        else:
            matrix = embed_texts_batch([c["text"] for c in chunks], dim=self.dim)
            vectors = [matrix[i].tolist() for i in range(len(chunks))]

        rows = [
            (f"{repo_id}::{c['id']}", repo_id, c["file"], c["start_line"], c["text"], json.dumps(vec))
            for c, vec in zip(chunks, vectors)
        ]
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO chunks (id, repo_id, file, start_line, text, vector) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def commit(self) -> None:
        with self._lock:
            self.conn.commit()

    def count(self, repo_id: str) -> int:
        with self._lock:
            cur = self.conn.execute("SELECT COUNT(*) FROM chunks WHERE repo_id = ?", (repo_id,))
            return int(cur.fetchone()[0])

    def query(
        self,
        repo_id: str,
        query_text: str,
        top_k: int = 5,
        file_prefix: str | None = None,
        file_extension: str | None = None,
        hybrid: bool = True,
        keyword_weight: float = 0.3,
    ) -> list[dict]:
        """Retrieve the top-k most relevant chunks for `query_text`.

        - **Metadata filtering**: `file_prefix` restricts results to chunks
          whose file path starts with a given prefix (e.g. "src/auth/");
          `file_extension` restricts to a given extension (e.g. "py").
        - **Hybrid retrieval**: by default, blends the semantic cosine
          score with a lexical keyword-overlap score
          (`score = (1 - keyword_weight) * cosine + keyword_weight * keyword`),
          which helps for queries containing exact identifiers/rule names
          that the hashing-trick embedding alone under-weights. Set
          `hybrid=False` for pure semantic search.
        """
        if not query_text.strip():
            return []
        q_vec = embed_text(query_text, dim=self.dim)

        sql = "SELECT id, file, start_line, text, vector FROM chunks WHERE repo_id = ?"
        params: list = [repo_id]
        if file_prefix:
            sql += " AND file LIKE ?"
            params.append(f"{file_prefix}%")
        if file_extension:
            sql += " AND file LIKE ?"
            params.append(f"%.{file_extension.lstrip('.')}")

        with self._lock:
            cur = self.conn.execute(sql, params)
            rows = cur.fetchall()
        scored = []
        for _id, file, start_line, text, vector_json in rows:
            vec = np.array(json.loads(vector_json), dtype=np.float32)
            semantic_score = cosine_similarity(q_vec, vec)
            if hybrid:
                lexical_score = keyword_overlap_score(query_text, text)
                score = (1 - keyword_weight) * semantic_score + keyword_weight * lexical_score
            else:
                score = semantic_score
            scored.append({
                "file": file, "start_line": start_line, "text": text,
                "score": score, "semantic_score": semantic_score,
            })
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:top_k]

    def batch_query(
        self,
        repo_id: str,
        query_texts: list[str],
        top_k: int = 5,
        **kwargs,
    ) -> dict[str, list[dict]]:
        """Run multiple queries against the same repo, loading and
        scoring chunks once per query rather than requiring N separate
        `query()` calls from the caller — useful when an agent needs
        context for several findings/functions in one pass (e.g. Fix
        Agent batch-processing top findings)."""
        return {q: self.query(repo_id, q, top_k=top_k, **kwargs) for q in query_texts}

    def similar_chunks(self, repo_id: str, min_score: float = 0.92) -> list[tuple[dict, dict]]:
        """Find near-duplicate chunk pairs (used by the Quality Agent to
        flag possible duplicated code)."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT id, file, start_line, text, vector FROM chunks WHERE repo_id = ?", (repo_id,)
            )
            rows_raw = cur.fetchall()
        rows = [
            {"id": r[0], "file": r[1], "start_line": r[2], "text": r[3],
             "vector": np.array(json.loads(r[4]), dtype=np.float32)}
            for r in rows_raw
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
