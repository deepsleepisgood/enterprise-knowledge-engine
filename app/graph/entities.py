"""Entity resolution (BUILD_PLAN Phase 2c), after Graphiti: candidates, then LLM confirmation.

1. Exact alias match (normalised) within the type.
2. Candidates by name similarity (trigram or Python) and embedding, same type.
3. One clear candidate (name similarity >= HIGH_NAME or cosine >= HIGH_COS) merges with no LLM.
4. Ambiguous candidates go to a cached MODEL_FAST confirmation.
5. No candidate: a new entity. Every surface form is recorded as an alias.
A wrong merge is worse than a missed one, so the bar to merge without the LLM is high.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.store import entities as store
from app.store.base import norm_name

PROMPT_VERSION = "entity-confirm-v1"
HIGH_NAME, HIGH_COS = 0.92, 0.95
LOW_NAME, LOW_COS = 0.6, 0.82
GENERIC_SUFFIXES = {
    "ltd",
    "limited",
    "pvt",
    "private",
    "inc",
    "llc",
    "plc",
    "co",
    "corp",
    "company",
    "the",
    "team",
    "dept",
    "department",
}


class _Same(BaseModel):
    same: bool
    reason: str


def _core(name: str) -> str:
    return " ".join(w for w in norm_name(name).split() if w not in GENERIC_SUFFIXES)


def name_similarity(a: str, b: str) -> float:
    ca, cb = _core(a), _core(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    ta, tb = set(ca.split()), set(cb.split())
    # One name's words all inside the other's ("Northwind" vs "Northwind Builders").
    if ta <= tb or tb <= ta:
        return max(0.85, SequenceMatcher(None, ca, cb).ratio())
    return SequenceMatcher(None, ca, cb).ratio()


def acronym(name: str) -> str:
    return "".join(w[0] for w in _core(name).split() if w)


def norm_type(t: str | None, known: list[str]) -> str:
    t = re.sub(r"[^a-z0-9]+", "_", (t or "other").lower()).strip("_")
    t = t[:-1] if t.endswith("s") and t[:-1] in known else t
    return t if t else "other"


class Resolver:
    def __init__(
        self,
        session: Session,
        structured_fn: Callable[..., Any] | None = None,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    ) -> None:
        self.s = session
        self.structured = structured_fn
        self.embed = embed_fn
        self.decisions: list[dict[str, Any]] = []
        self._memo: dict[tuple[str, str], str] = {}

    def _confirm(self, name: str, cand: store.EntityRow, type_: str) -> bool:
        if self.structured is None:
            return False
        out: _Same = self.structured(
            f"Entity type: {type_}\nName A: {name}\nName B: {cand.name} "
            f"(also called: {', '.join(cand.aliases[:6])})\n"
            "Do A and B refer to the same real-world entity in this organisation's documents? "
            "Abbreviations and short forms count as the same; different units, branches, "
            "people or products do not.",
            _Same,
            model="fast",
            prompt_version=PROMPT_VERSION,
            max_tokens=2048,
        )
        return out.same

    def resolve(self, name: str, type_: str, episode_id: str | None = None) -> str:
        name = re.sub(r"\s+", " ", name).strip()
        memo_key = (type_, norm_name(name))
        if memo_key in self._memo:
            return self._memo[memo_key]
        eid = store.by_alias(self.s, name, type_)
        decision = "alias"
        if eid is None:
            vec = self.embed([f"{type_}: {name}"])[0] if self.embed else None
            cands = store.candidates(self.s, name, type_, vec)
            best, best_score, how = None, 0.0, ""
            for c in cands:
                ns = max(name_similarity(name, a) for a in [c.name, *c.aliases])
                acr = any(
                    acronym(a) == norm_name(name).replace(" ", "") and len(name) >= 2
                    for a in [c.name, *c.aliases]
                )
                score = max(ns, c.score if vec is not None else 0.0)
                if acr:
                    score = max(score, 0.8)
                if score > best_score:
                    best, best_score, how = c, score, ("acronym" if acr else "name/embedding")
            if best is not None and (
                best_score >= HIGH_NAME
                or (vec is not None and best.score >= HIGH_COS and best_score >= HIGH_COS)
            ):
                eid, decision = best.id, f"merged ({how} {best_score:.2f})"
            elif best is not None and best_score >= LOW_NAME and self._confirm(name, best, type_):
                eid, decision = best.id, f"merged after LLM confirm ({best_score:.2f})"
            if eid is None:
                eid = store.create(self.s, type_, name, embedding=vec, episode_id=episode_id)
                decision = "new"
        store.add_alias(self.s, eid, name, episode_id)
        self._memo[memo_key] = eid
        self.decisions.append({"name": name, "type": type_, "entity": eid, "decision": decision})
        return eid

    def canonical_name(self, entity_id: str) -> str:
        row = store.get(self.s, entity_id)
        return row.name if row else entity_id
