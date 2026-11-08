"""Ablation configurations A-C (TEST_PLAN level 6). D is the full system (app.answer.ask).

A  naive vector RAG: fixed ~500-token chunks of each file's text, top 5, one prompt, no metadata
B  the whole corpus in context (about 9k tokens), no authority layer
C  B plus the authority graph: which facts are current, superseded or overridden, and practice

Same answer model as D (MODEL_SMART, reasoning off). Each returns an answer card shape so the
same metrics apply.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.db import session_scope

PROMPT_VERSION = "ablation-v1"
CHUNK_CHARS = 2000  # ~500 tokens
_lock = threading.Lock()

SYSTEM = """You answer an accounts staff member's question using only the material below.
If the material does not answer it, return status "unsupported". Cite the file and the section
(or timestamp) you used for each point. Be brief: the direct answer first, then the rule.
For a calculation, work it out step by step and give the result."""


class Cite(BaseModel):
    file: str
    locator: str = Field("", description="Section number, part or timestamp, if known")


class Out(BaseModel):
    status: Literal["answered", "unsupported"]
    answer: str = ""
    decision: str | None = None
    citations: list[Cite] = Field(default_factory=list)


@lru_cache(maxsize=1)
def corpus() -> list[tuple[str, str, str]]:
    """(file, locator, text) of every live leaf passage, in document order."""
    with session_scope() as s:
        rows = s.execute(
            text(
                "SELECT e.source_uri, p.locator, p.text FROM passages p "
                "JOIN episodes e ON e.id = p.episode_id JOIN sources src ON src.id = p.source_id "
                "WHERE p.retired_at IS NULL AND p.segment_kind <> 'record' "
                "AND p.meta->>'leaf' = 'true' ORDER BY e.source_uri, src.ordinal, p.ordinal"
            )
        ).all()
    return [(f, loc, t) for f, loc, t in rows]


@lru_cache(maxsize=1)
def chunks() -> tuple[list[tuple[str, str]], list[list[float]]]:
    """Fixed-size chunks of each file's plain text (no headers, no structure) and embeddings."""
    from app.core.embed import embed

    by_file: dict[str, list[str]] = {}
    for f, _, t in corpus():
        by_file.setdefault(f, []).append(t)
    out = []
    for f, texts in by_file.items():
        body = "\n".join(texts)
        out += [(f, body[i : i + CHUNK_CHARS]) for i in range(0, len(body), CHUNK_CHARS)]
    return out, embed([c for _, c in out])


def whole_corpus() -> str:
    lines, last = [], None
    for f, loc, t in corpus():
        if f != last:
            lines.append(f"\n=== {f} ===")
            last = f
        lines.append(f"[{loc}] {t}")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def authority_layer() -> str:
    """Rules by status (current / superseded / overridden) and practice, with their sources."""
    with session_scope() as s:
        rows = s.execute(
            text(
                "SELECT f.status, f.kind, f.statement, src.short_label, p.locator, "
                "f.scope->>'client' FROM facts f LEFT JOIN sources src ON src.id = f.source_id "
                "LEFT JOIN passages p ON p.id = f.passage_id WHERE f.retracted_at IS NULL "
                "AND f.status IN ('current','superseded','overridden') "
                "AND f.attribute NOT LIKE 'other:%' ORDER BY f.attribute, f.status"
            )
        ).all()
    out = []
    for status, kind, stmt, label, loc, client in rows:
        tag = "PRACTICE (tip, not a rule)" if kind == "practice" else status.upper()
        scope = f" [only {client}]" if client and client != "all" else ""
        out.append(f"- {tag}: {stmt}{scope} ({label or ''} {loc or ''})")
    return "\n".join(out)


def _card(o: Out) -> dict[str, Any]:
    return {
        "status": o.status,
        "route": "ablation",
        "rule": {
            "text": o.answer if o.status == "answered" else "",
            "citations": [
                {"file": c.file, "locator": c.locator, "short_label": c.locator}
                for c in o.citations
            ],
        },
        "decision": o.decision,
        "working": None,
        "older_sources": [],
        "expert_tip": None,
        "route_to": None,
    }


def answer(config: str, question: str, structured_fn: Callable[..., Any]) -> dict[str, Any]:
    if config == "A":
        from app.core.embed import cosine, embed

        with _lock:
            cs, vecs = chunks()
        qv = embed([question])[0]
        top = sorted(range(len(cs)), key=lambda i: -cosine(qv, vecs[i]))[:5]
        material = "\n\n".join(f"--- {cs[i][0]} ---\n{cs[i][1]}" for i in top)
    else:
        material = whole_corpus()
        if config == "C":
            material += (
                "\n\nAUTHORITY LAYER (which statements are in force; the most authoritative "
                "current source wins, superseded values are no longer the rule):\n"
                + authority_layer()
            )
    out: Out = structured_fn(
        f"Question: {question}\n\nMaterial:\n{material}",
        Out,
        system=SYSTEM,
        model="smart",
        prompt_version=f"{PROMPT_VERSION}-{config}",
        max_tokens=4096,
    )
    return _card(out)
