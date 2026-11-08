"""Cross-encoder reranking (fastembed, local CPU). Model from RERANK_MODEL; "none" turns it off."""

from __future__ import annotations

import threading
from functools import lru_cache

from app.core.config import get_settings

_lock = threading.Lock()


def enabled() -> bool:
    return get_settings().rerank_model.strip().lower() not in ("", "none", "off")


@lru_cache(maxsize=1)
def _model():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(get_settings().rerank_model)


def rerank(query: str, docs: list[str]) -> list[float]:
    """One relevance score per doc (higher is better; raw logits, not probabilities)."""
    if not docs:
        return []
    with _lock:
        return [float(s) for s in _model().rerank(query, docs, batch_size=16)]
