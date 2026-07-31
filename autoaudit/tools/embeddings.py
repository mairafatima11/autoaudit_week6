"""Deterministic, dependency-light embeddings for the Repository Knowledge
Base. Uses a hashing trick over word tokens (a "poor man's" bag-of-words
embedding) so the RAG pipeline works fully offline with no model download —
see README "RAG / Repository Knowledge Base" for the rationale, and swap
this module for a hosted embedding API in production if desired.
"""
from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")


def tokenize(text: str) -> list[str]:

    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text.lower()):
        tokens.append(raw)
        tokens.extend(part for part in raw.split("_") if part and part != raw)
    return tokens


def embed_text(text: str, dim: int = 256) -> np.ndarray:
    """Hashing-trick bag-of-words embedding, L2-normalized."""
    vec = np.zeros(dim, dtype=np.float32)
    tokens = tokenize(text)
    if not tokens:
        return vec
    counts = Counter(tokens)
    for token, count in counts.items():
        idx = hash(token) % dim
        sign = 1.0 if (hash(token) // dim) % 2 == 0 else -1.0
        vec[idx] += sign * (1.0 + math.log(count))
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)
