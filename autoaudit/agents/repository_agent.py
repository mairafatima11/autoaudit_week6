"""Repository Agent: clones/reads the repo, builds the file/module map, and
populates the Repository Knowledge Base (vector store) with per-chunk
embeddings. Supports incremental re-indexing (Week 7 performance scope):
unchanged files' chunks/embeddings are left untouched on repeat runs.
"""
from __future__ import annotations

import hashlib

from ..memory.vector_store import VectorStore
from ..tools import repo_reader
from ..tools.repo_reader import normalize_source
from ..tools.cache import Cache
from ..tracing import Tracer


def repo_id_for(source: str) -> str:
    """Stable id for a repo across runs, so audit history/vector store can
    key on it regardless of exactly how the source was phrased.

    Two bugs lived in the previous one-liner (`source.rstrip("/").rstrip(".git")`):

    1. **`rstrip` strips characters, not a suffix.** `.rstrip(".git")`
       removes *any* trailing run of `.`, `g`, `i` or `t`, so
       `.../pytest` became `.../pytes` and `.../config` became `.../conf`.
       Any repository whose name ends in one of those characters got a
       mangled, though at least self-consistent, id.
    2. **No whitespace normalization**, so a pasted URL with a leading
       space hashed to a different id than the same URL without one —
       silently splitting one repository's history into two.
    """
    normalized = normalize_source(source).rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[: -len(".git")].rstrip("/")
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


class RepositoryAgent:
    def __init__(
        self,
        vector_store: VectorStore,
        tracer: Tracer,
        max_file_bytes: int = 400_000,
        cache: Cache | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.tracer = tracer
        self.max_file_bytes = max_file_bytes
        self.cache = cache

    def build_knowledge_base(self, source: str):
        """Returns (repo_id, file_records, temp_dir_or_None, resolved_root)."""
        self.tracer.log("repository_agent", "read_repo.start", source=source)
        records, resolved_root, temp_dir = repo_reader.read_repo(source, max_file_bytes=self.max_file_bytes)
        repo_id = repo_id_for(source)

        if self.cache is None:
            self.vector_store.clear_repo(repo_id)
            targets = records
            skipped = 0
        else:
            pairs = [(r.path, r.content) for r in records]
            changed_paths, unchanged_paths = self.cache.changed_files(repo_id, pairs)
            changed_set = set(changed_paths)
            targets = [r for r in records if r.path in changed_set]
            skipped = len(unchanged_paths)
            for path in changed_paths:
                self.vector_store.delete_file(repo_id, path)
            self.cache.record_file_hashes(repo_id, pairs)

        all_chunk_dicts = [
            {"id": chunk.id, "file": chunk.file, "start_line": chunk.start_line, "text": chunk.text}
            for rec in targets
            for chunk in rec.chunks
        ]
        self.vector_store.add_chunks_batch(repo_id, all_chunk_dicts, cache=self.cache)
        n_chunks = len(all_chunk_dicts)
        self.vector_store.commit()

        self.tracer.log(
            "repository_agent", "read_repo.done",
            repo_id=repo_id, files=len(records), files_reindexed=len(targets),
            files_skipped_unchanged=skipped, chunks=n_chunks,
        )
        return repo_id, records, temp_dir, resolved_root
