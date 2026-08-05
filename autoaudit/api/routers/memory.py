"""Memory / Knowledge Base API.

The Memory page is specified to show the repository knowledge base — chunk
counts, embedding dimensionality, per-file breakdown and a way to query it —
but no endpoint existed to serve any of that, so the page could only ever
render trend charts. These endpoints expose the VectorStore that the
Repository Agent has been populating all along.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_audit_history, get_config
from ...config import Config
from ...memory.audit_history import AuditHistory
from ...memory.vector_store import VectorStore

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _open_store(config: Config) -> VectorStore:
    return VectorStore(config.data_dir / "vector_store.db", dim=config.embedding_dim)


@router.get("/knowledge-base")
def knowledge_base(
    repo_id: str | None = None,
    config: Config = Depends(get_config),
    history: AuditHistory = Depends(get_audit_history),
):
    """Knowledge-base statistics: indexed chunks, embedding dimension, and
    the files contributing the most chunks. Scoped to `repo_id` when given,
    otherwise summarised across every indexed repository."""
    store = _open_store(config)
    try:
        if repo_id:
            repo_ids = [repo_id]
        else:
            repo_ids = [r["repo_id"] for r in history.repositories()]

        per_repo = []
        total_chunks = 0
        for rid in repo_ids:
            count = store.count(rid)
            total_chunks += count
            per_repo.append({"repo_id": rid, "chunks": count})

        top_files: list[dict] = []
        if repo_id:
            with store._lock:  # noqa: SLF001 - read-only stats query on the same connection
                cur = store.conn.execute(
                    """SELECT file, COUNT(*), SUM(LENGTH(text))
                       FROM chunks WHERE repo_id = ?
                       GROUP BY file ORDER BY COUNT(*) DESC LIMIT 15""",
                    (repo_id,),
                )
                top_files = [
                    {"file": r[0], "chunks": r[1], "characters": r[2] or 0}
                    for r in cur.fetchall()
                ]

        return {
            "repo_id": repo_id,
            "embedding_dim": config.embedding_dim,
            "total_chunks": total_chunks,
            "indexed_repositories": len(per_repo),
            "per_repo": per_repo,
            "top_files": top_files,
        }
    finally:
        store.close()
        history.close()


@router.get("/search")
def search_knowledge_base(
    repo_id: str,
    q: str,
    top_k: int = 8,
    file_prefix: str | None = None,
    file_extension: str | None = None,
    hybrid: bool = True,
    config: Config = Depends(get_config),
):
    """Query the knowledge base directly — the retrieval layer the agents
    use, exposed so the Memory page can demonstrate that the RAG index is
    real and inspectable rather than just reporting a chunk count."""
    if not q.strip():
        raise HTTPException(status_code=422, detail="Query `q` must not be empty.")
    store = _open_store(config)
    try:
        results = store.query(
            repo_id, q, top_k=max(1, min(top_k, 50)),
            file_prefix=file_prefix, file_extension=file_extension, hybrid=hybrid,
        )
        return {
            "repo_id": repo_id,
            "query": q,
            "hybrid": hybrid,
            "results": [
                {
                    "file": r["file"],
                    "start_line": r["start_line"],
                    "score": round(float(r["score"]), 4),
                    "semantic_score": round(float(r["semantic_score"]), 4),
                    "text": r["text"][:1200],
                }
                for r in results
            ],
        }
    finally:
        store.close()
