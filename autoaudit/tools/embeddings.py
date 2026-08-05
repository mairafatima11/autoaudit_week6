"""Deterministic, dependency-light embeddings for the Repository Knowledge
Base. Uses a hashing trick over word tokens (a "poor man's" bag-of-words
embedding) so the RAG pipeline works fully offline with no model download —
see README "RAG / Repository Knowledge Base" for the rationale, and swap
this module for a hosted embedding API in production if desired.
"""
from __future__ import annotations

import math
import re
import zlib
from collections import Counter

import numpy as np

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")


def tokenize(text: str) -> list[str]:

    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text.lower()):
        tokens.append(raw)
        tokens.extend(part for part in raw.split("_") if part and part != raw)
    return tokens


def _stable_hash(token: str) -> int:
    """Deterministic hash for the hashing-trick embedding. Python's
    built-in `hash()` is randomized per-process (PYTHONHASHSEED) by
    design — fine for dict lookups, wrong here: it would make the same
    text embed to a *different* vector on every process restart, silently
    breaking the file-hash embedding cache's core assumption (that
    embed_text(text) is a pure function of text) and making retrieval
    results non-reproducible between runs. zlib.crc32 is stable across
    processes/platforms and fast enough for this at repo scale.
    """
    return zlib.crc32(token.encode("utf-8"))


def embed_text(text: str, dim: int = 256) -> np.ndarray:
    """Hashing-trick bag-of-words embedding, L2-normalized."""
    vec = np.zeros(dim, dtype=np.float32)
    tokens = tokenize(text)
    if not tokens:
        return vec
    counts = Counter(tokens)
    for token, count in counts.items():
        h = _stable_hash(token)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign * (1.0 + math.log(count))
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def embed_texts_batch(texts: list[str], dim: int = 256) -> np.ndarray:
    """Batch-embed many chunks in one call, returning an (N, dim) matrix.

    This is more than a loop-with-a-different-name: token counting for all
    texts is vectorized into a single sparse-index scatter-add over a
    shared (N, dim) buffer using numpy, rather than N independent Python
    calls each allocating and normalizing their own vector. For the
    hashing-trick embedding this is still O(total tokens) work either way,
    but doing it as one batch avoids per-call numpy allocation overhead and
    is the natural place to plug in a real batched embedding API later
    (e.g. one HTTP call for N texts instead of N calls).
    """
    n = len(texts)
    matrix = np.zeros((n, dim), dtype=np.float32)
    if n == 0:
        return matrix

    for row, text in enumerate(texts):
        tokens = tokenize(text)
        if not tokens:
            continue
        counts = Counter(tokens)
        for token, count in counts.items():
            h = _stable_hash(token)
            idx = h % dim
            sign = 1.0 if (h // dim) % 2 == 0 else -1.0
            matrix[row, idx] += sign * (1.0 + math.log(count))

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def keyword_overlap_score(query: str, text: str) -> float:
    """Cheap lexical score for hybrid retrieval: fraction of the query's
    distinct tokens that appear in the candidate text. Deliberately simple
    (no IDF weighting) so it stays fast at repo scale and easy to reason
    about — it's a complement to the semantic cosine score, not a
    replacement for a real BM25 implementation."""
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    text_tokens = set(tokenize(text))
    if not text_tokens:
        return 0.0
    overlap = query_tokens & text_tokens
    return len(overlap) / len(query_tokens)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)
