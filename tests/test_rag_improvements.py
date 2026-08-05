from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from autoaudit.memory.vector_store import VectorStore
from autoaudit.tools.cache import Cache
from autoaudit.tools.embeddings import embed_text, embed_texts_batch, keyword_overlap_score


# ---- batch embedding ---------------------------------------------------------

def test_embed_texts_batch_matches_single_embed():
    texts = ["def get_user(user_id): pass", "API_KEY = 'secret'", "import os", ""]
    batch = embed_texts_batch(texts, dim=64)
    assert batch.shape == (4, 64)
    for i, t in enumerate(texts):
        assert np.allclose(embed_text(t, dim=64), batch[i])


def test_embed_texts_batch_empty_list():
    result = embed_texts_batch([], dim=64)
    assert result.shape == (0, 64)


def test_embed_text_deterministic_across_processes():
    """Regression test for a real bug: embed_text used Python's built-in
    hash() for the hashing trick, which is randomized per-process
    (PYTHONHASHSEED) by default — meaning the same text embedded to a
    different vector on every process restart, silently breaking the
    file-hash embedding cache's core assumption and making retrieval
    non-reproducible across server restarts. Fixed by switching to
    zlib.crc32. This test spawns a fresh subprocess (a real different
    PYTHONHASHSEED) and checks the embedding matches this process's."""
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent

    text = "def get_user(user_id): return db.find(user_id)"
    here_vec = embed_text(text, dim=64)

    result = subprocess.run(
        [sys.executable, "-c", (
            "from autoaudit.tools.embeddings import embed_text; "
            f"v = embed_text({text!r}, dim=64); "
            "print(','.join(f'{x:.6f}' for x in v))"
        )],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    assert result.returncode == 0, result.stderr
    other_vec = np.array([float(x) for x in result.stdout.strip().split(",")], dtype=np.float32)
    assert np.allclose(here_vec, other_vec), "embeddings differ across processes — non-determinism regression"


# ---- keyword overlap ----------------------------------------------------------

def test_keyword_overlap_score_high_for_matching_terms():
    score = keyword_overlap_score("hardcoded api key secret", "API_KEY = 'sk-live-123'")
    assert score > 0


def test_keyword_overlap_score_zero_for_no_overlap():
    assert keyword_overlap_score("hardcoded api key secret", "import os") == 0.0


def test_keyword_overlap_score_empty_query():
    assert keyword_overlap_score("", "anything") == 0.0


# ---- VectorStore: batch insert, hybrid retrieval, metadata filtering, batch query --

@pytest.fixture()
def populated_store(tmp_path: Path):
    store = VectorStore(tmp_path / "vs.db", dim=64)
    chunks = [
        {"id": "c1", "file": "src/auth/login.py", "start_line": 1, "text": "def login(user, password): check_secret_key(password)"},
        {"id": "c2", "file": "src/auth/login.py", "start_line": 10, "text": "API_KEY = 'sk-live-hardcoded-secret'"},
        {"id": "c3", "file": "src/utils/math.py", "start_line": 1, "text": "def add(a, b): return a + b"},
        {"id": "c4", "file": "README.md", "start_line": 1, "text": "This project has no secrets here, just docs."},
    ]
    store.add_chunks_batch("repo1", chunks)
    store.commit()
    yield store
    store.close()


def test_add_chunks_batch_inserts_all_chunks(populated_store: VectorStore):
    assert populated_store.count("repo1") == 4


def test_add_chunks_batch_empty_list_noop(tmp_path: Path):
    store = VectorStore(tmp_path / "vs2.db", dim=64)
    store.add_chunks_batch("repo1", [])  # must not raise
    assert store.count("repo1") == 0
    store.close()


def test_add_chunks_batch_reuses_cache(tmp_path: Path):
    store = VectorStore(tmp_path / "vs3.db", dim=64)
    cache = Cache(tmp_path / "cache.db")
    chunks = [{"id": "c1", "file": "a.py", "start_line": 1, "text": "def foo(): pass"}]

    store.add_chunks_batch("repo1", chunks, cache=cache)
    store.commit()
    # A second insert of the same content should hit the cache rather than recompute.
    store.add_chunks_batch("repo1", chunks, cache=cache)
    store.commit()
    assert store.count("repo1") == 1  # INSERT OR REPLACE — same id, still one row
    store.close()
    cache.close()


def test_query_metadata_filter_by_prefix(populated_store: VectorStore):
    results = populated_store.query("repo1", "secret", top_k=10, file_prefix="src/auth/")
    assert all(r["file"].startswith("src/auth/") for r in results)
    assert len(results) == 2


def test_query_metadata_filter_by_extension(populated_store: VectorStore):
    results = populated_store.query("repo1", "secret", top_k=10, file_extension="py")
    assert all(r["file"].endswith(".py") for r in results)
    assert all("README" not in r["file"] for r in results)


def test_query_hybrid_boosts_keyword_matches(populated_store: VectorStore):
    hybrid_results = populated_store.query("repo1", "hardcoded secret key", top_k=4, hybrid=True)
    semantic_results = populated_store.query("repo1", "hardcoded secret key", top_k=4, hybrid=False)

    hybrid_top = hybrid_results[0]
    semantic_top = semantic_results[0]
    # Both should surface the API_KEY chunk as most relevant; hybrid score
    # should be >= the pure semantic score for that same chunk since the
    # keyword component only adds, never subtracts (weights are >= 0).
    assert hybrid_top["file"] == "src/auth/login.py"
    assert hybrid_top["score"] >= hybrid_top["semantic_score"]
    assert semantic_top["file"] == "src/auth/login.py"


def test_query_hybrid_can_be_disabled(populated_store: VectorStore):
    results = populated_store.query("repo1", "secret", top_k=1, hybrid=False)
    assert results[0]["score"] == results[0]["semantic_score"]


def test_batch_query_runs_multiple_queries(populated_store: VectorStore):
    results = populated_store.batch_query("repo1", ["secret key", "add numbers"], top_k=2)
    assert set(results.keys()) == {"secret key", "add numbers"}
    assert len(results["secret key"]) <= 2
    assert len(results["add numbers"]) <= 2
    # "add numbers" should surface the math.py chunk near the top.
    assert results["add numbers"][0]["file"] == "src/utils/math.py"


def test_query_returns_empty_for_blank_query(populated_store: VectorStore):
    assert populated_store.query("repo1", "   ") == []
