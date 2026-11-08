"""Embedding index for retrieval: passages (context header + text), facts, entities.

Runs after parsing and after extraction (`index_embeddings` job) and from the build script.
Only rows without an embedding are embedded, so re-running is cheap.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.db import session_scope
from app.store import episodes as estore
from app.store import search
from app.worker import handler

EmbedFn = Callable[[list[str]], list[list[float]]]
BATCH = 256


def _default_embed() -> EmbedFn:
    from app.core.embed import embed

    return embed


def index_all(embed_fn: EmbedFn | None = None) -> dict[str, int]:
    embed = embed_fn or _default_embed()
    counts = {"passages": 0, "facts": 0, "entities": 0}
    while True:
        with session_scope() as s:
            todo = search.passages_without_embedding(s, limit=BATCH)
            if not todo:
                break
            vecs = embed([t[:4000] for _, t in todo])
            estore.set_passage_embeddings(s, {i: v for (i, _), v in zip(todo, vecs, strict=True)})
            counts["passages"] += len(todo)
    while True:
        with session_scope() as s:
            todo_f = search.facts_without_embedding(s, limit=BATCH)
            if not todo_f:
                break
            vecs = embed([t for _, t in todo_f])
            search.set_fact_embeddings(s, {i: v for (i, _), v in zip(todo_f, vecs, strict=True)})
            counts["facts"] += len(todo_f)
    while True:
        with session_scope() as s:
            todo_e = search.entities_without_embedding(s, limit=BATCH)
            if not todo_e:
                break
            vecs = embed([t for _, t in todo_e])
            search.set_entity_embeddings(s, {i: v for (i, _), v in zip(todo_e, vecs, strict=True)})
            counts["entities"] += len(todo_e)
    return counts


@handler("index_embeddings")
def index_job(payload: dict[str, Any]) -> dict[str, Any]:
    return index_all()
