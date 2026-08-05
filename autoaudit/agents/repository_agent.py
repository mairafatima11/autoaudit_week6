"""Repository Agent: clones/reads the repo, builds the file/module map, and
populates the Repository Knowledge Base (vector store) with per-chunk
embeddings.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..memory.vector_store import VectorStore
from ..tools import repo_reader
from ..tracing import Tracer


def repo_id_for(source: str) -> str:
    """Stable id for a repo across runs, so audit history/vector store can
    key on it regardless of exactly how the CLI arg is phrased."""
    normalized = source.rstrip("/").rstrip(".git")
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


class RepositoryAgent:
    def __init__(self, vector_store: VectorStore, tracer: Tracer, max_file_bytes: int = 400_000) -> None:
        self.vector_store = vector_store
        self.tracer = tracer
        self.max_file_bytes = max_file_bytes

    def build_knowledge_base(self, source: str):
        """Returns (repo_id, file_records, temp_dir_or_None, resolved_root)."""
        self.tracer.log("repository_agent", "read_repo.start", source=source)
        records, resolved_root, temp_dir = repo_reader.read_repo(source, max_file_bytes=self.max_file_bytes)
        repo_id = repo_id_for(source)

        self.vector_store.clear_repo(repo_id)
        n_chunks = 0
        for rec in records:
            for chunk in rec.chunks:
                self.vector_store.add_chunk(repo_id, chunk.id, chunk.file, chunk.start_line, chunk.text)
                n_chunks += 1
        self.vector_store.commit()

        self.tracer.log(
            "repository_agent", "read_repo.done",
            repo_id=repo_id, files=len(records), chunks=n_chunks,
        )
        return repo_id, records, temp_dir, resolved_root
