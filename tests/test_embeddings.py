from __future__ import annotations

import numpy as np

from autoaudit.tools import embeddings


def test_embed_text_is_deterministic():
    v1 = embeddings.embed_text("hardcoded api key secret")
    v2 = embeddings.embed_text("hardcoded api key secret")
    assert np.allclose(v1, v2)


def test_embed_text_is_normalized():
    v = embeddings.embed_text("some function that does something useful")
    norm = np.linalg.norm(v)
    assert abs(norm - 1.0) < 1e-4 or norm == 0.0


def test_empty_text_returns_zero_vector():
    v = embeddings.embed_text("")
    assert np.allclose(v, np.zeros_like(v))


def test_similar_text_scores_higher_than_unrelated():
    a = embeddings.embed_text("def get_user(user_id): return database.find(user_id)")
    b = embeddings.embed_text("def fetch_user(uid): return database.find(uid)")
    c = embeddings.embed_text("import matplotlib.pyplot as plt; plt.show()")

    sim_ab = embeddings.cosine_similarity(a, b)
    sim_ac = embeddings.cosine_similarity(a, c)
    assert sim_ab > sim_ac


def test_cosine_similarity_zero_vector_is_zero():
    a = np.zeros(256, dtype=np.float32)
    b = embeddings.embed_text("anything")
    assert embeddings.cosine_similarity(a, b) == 0.0


def test_tokenize_splits_snake_case():
    tokens = embeddings.tokenize("hardcoded_api_key = 'x'")
    assert "api" in tokens
    assert "key" in tokens
