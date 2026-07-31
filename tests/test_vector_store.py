from __future__ import annotations

from pathlib import Path

from autoaudit.memory.vector_store import VectorStore


def test_add_and_query_finds_relevant_chunk(tmp_path: Path):
    store = VectorStore(tmp_path / "vs.db", dim=64)
    store.add_chunk("repoA", "f1:1", "a.py", 1, "def get_user(user_id): return db.find(user_id)")
    store.add_chunk("repoA", "f2:1", "b.py", 1, "import matplotlib.pyplot as plt")
    store.commit()

    results = store.query("repoA", "fetch a user by id from the database", top_k=1)
    assert results
    assert results[0]["file"] == "a.py"
    store.close()


def test_query_empty_string_returns_empty(tmp_path: Path):
    store = VectorStore(tmp_path / "vs.db")
    store.add_chunk("repoA", "f1:1", "a.py", 1, "def foo(): pass")
    store.commit()
    assert store.query("repoA", "", top_k=3) == []
    store.close()


def test_query_scoped_to_repo_id(tmp_path: Path):
    store = VectorStore(tmp_path / "vs.db")
    store.add_chunk("repoA", "f1:1", "a.py", 1, "def get_user(user_id): pass")
    store.commit()
    assert store.count("repoA") == 1
    assert store.count("repoB") == 0
    store.close()

def test_clear_repo_removes_only_that_repo(tmp_path: Path):
    store = VectorStore(tmp_path / "vs.db")
    store.add_chunk("repoA", "f1:1", "a.py", 1, "def a(): pass")
    store.add_chunk("repoB", "f1:1", "a.py", 1, "def b(): pass")
    store.commit()
    store.clear_repo("repoA")
    assert store.count("repoA") == 0
    assert store.count("repoB") == 1
    store.close()


def test_similar_chunks_detects_near_duplicates(tmp_path: Path):
    store = VectorStore(tmp_path / "vs.db")
    body = "\n".join(f"    total += item * {i}" for i in range(20))
    text_a = f"def compute_a(data):\n{body}\n    return total"
    text_b = f"def compute_b(data):\n{body}\n    return total"
    store.add_chunk("repoA", "a:1", "a.py", 1, text_a)
    store.add_chunk("repoA", "b:1", "b.py", 1, text_b)
    store.commit()

    pairs = store.similar_chunks("repoA", min_score=0.9)
    assert len(pairs) == 1
    store.close()


def test_similar_chunks_ignores_short_chunks(tmp_path: Path):
    store = VectorStore(tmp_path / "vs.db")
    store.add_chunk("repoA", "a:1", "a.py", 1, "x = 1")
    store.add_chunk("repoA", "b:1", "b.py", 1, "x = 1")
    store.commit()
    pairs = store.similar_chunks("repoA", min_score=0.5)
    assert pairs == []
    store.close()
