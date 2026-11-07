"""Local embeddings (fastembed, BAAI/bge-small-en-v1.5, 384 dims, CPU)."""

from __future__ import annotations

import threading
from functools import lru_cache

MODEL = "BAAI/bge-small-en-v1.5"
_lock = threading.Lock()


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL)


@lru_cache(maxsize=4096)
def _one(text: str) -> tuple[float, ...]:
    with _lock:
        vec = next(iter(_model().embed([text])))
    return tuple(float(x) for x in vec)


def embed(texts: list[str]) -> list[list[float]]:
    """Normalised vectors (cosine = dot product). Small inputs are cached in-process."""
    if len(texts) <= 8:
        return [list(_one(t)) for t in texts]
    with _lock:
        return [[float(x) for x in v] for v in _model().embed(texts, batch_size=64)]


def cosine(a: list[float], b: list[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=True)))
