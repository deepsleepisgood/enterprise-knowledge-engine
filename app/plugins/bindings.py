"""Plug-in bindings (BUILD_PLAN Phase 3): map a plug-in's parameters to schema attributes.

bind():  exact attribute key first; otherwise candidates by embedding and words, filtered by
         compatible value type, confirmed by MODEL_FAST (cached). Owner-confirmed bindings are
         never overwritten. Unresolved parameters are stored with no attribute (Setup lists them).
BoundRules: the `Rules` lookup plug-in calculators receive. A parameter without a binding raises
         RuleNotFound; there is no default.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.graph.ontology import Attribute, Ontology
from app.graph.rules import RuleNotFound, RuleValue, get_rule
from app.plugins.registry import Plugin
from app.store import facts as fstore
from app.store import kb

PROMPT_VERSION = "bind-v2"
NUMERIC = {"percentage", "money", "days", "number"}
COMPATIBLE = {
    "percentage": {"percentage", "number"},
    "money": {"money", "number"},
    "days": {"days", "number"},
    "number": NUMERIC,
    "list": {"list", "text", "enum"},
    "text": {"text", "enum", "list", "date"},
}


class _Pick(BaseModel):
    choice: int = Field(description="Number of the matching attribute, or 0 if none matches")
    reason: str


@dataclass
class BindResult:
    param: str
    attribute: str | None
    confidence: float
    method: str


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def _attr_text(a: Attribute, onto: Ontology) -> str:
    t = onto.topic(a.topic)
    return " ".join(
        [
            a.key.replace("_", " ").replace(".", " "),
            a.label,
            a.description,
            *a.synonyms,
            t.label if t else "",
            *((t.synonyms if t else [])[:6]),
        ]
    )


def bind(
    session: Session,
    plugin: Plugin,
    onto: Ontology,
    structured_fn: Callable[..., Any] | None = None,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[BindResult]:
    params = plugin.file("bindings.yaml").get("params", {})
    existing = {b.param: b for b in kb.get_bindings(session, plugin.name)}
    live = fstore.in_force_values(session)  # attribute -> values of rules in force now
    attrs = onto.attributes
    vecs = None
    if embed_fn is not None and attrs:
        vecs = embed_fn([_attr_text(a, onto) for a in attrs])
    out: list[BindResult] = []
    for param, spec in params.items():
        prev = existing.get(param)
        if prev is not None and prev.confirmed_by and prev.attribute_key:
            out.append(BindResult(param, prev.attribute_key, prev.confidence or 1.0, "owner"))
            continue
        want = spec.get("value_type", "text")
        if onto.attribute(param):
            res = BindResult(param, param, 1.0, "exact key")
        else:
            desc = f"{param.replace('_', ' ').replace('.', ' ')}: {spec.get('description', '')}"
            pv = embed_fn([desc])[0] if embed_fn is not None else None
            scored = []
            # A calculator reads rules in force: prefer attributes that have one.
            pool = [
                (i, a) for i, a in enumerate(attrs) if a.value_type in COMPATIBLE.get(want, {want})
            ]
            if any(a.key in live for _, a in pool):
                pool = [(i, a) for i, a in pool if a.key in live]
            for i, a in pool:
                words = len(_words(desc) & _words(_attr_text(a, onto))) / max(len(_words(desc)), 1)
                cos = sum(x * y for x, y in zip(pv, vecs[i], strict=True)) if pv and vecs else 0.0
                scored.append((0.6 * cos + 0.4 * words, a))
            scored.sort(key=lambda t: -t[0])
            top = [a for _, a in scored[:6]]
            res = BindResult(param, None, 0.0, "unresolved")
            if top and structured_fn is not None:
                lines = "\n".join(
                    f"{n}. {a.key} [{a.value_type}] {a.label}: {a.description} "
                    f"(in force now: {', '.join(live.get(a.key, [])) or 'nothing'})"
                    for n, a in enumerate(top, 1)
                )
                pick: _Pick = structured_fn(
                    f"A calculator needs this parameter:\n{desc} (type {want})\n\n"
                    f"Candidate attributes in the knowledge graph:\n{lines}\n\n"
                    "Which attribute holds exactly this value? Answer 0 if none does.",
                    _Pick,
                    model="fast",
                    prompt_version=PROMPT_VERSION,
                    max_tokens=2048,
                )
                if 1 <= pick.choice <= len(top):
                    res = BindResult(param, top[pick.choice - 1].key, 0.8, "embedding + LLM")
            elif scored and scored[0][0] >= 0.85:
                res = BindResult(param, scored[0][1].key, round(scored[0][0], 2), "embedding")
        kb.put_binding(
            session,
            plugin.name,
            param,
            attribute_key=res.attribute,
            confidence=res.confidence,
            confirmed_by=None,
            meta={"method": res.method, "value_type": want},
        )
        out.append(res)
    return out


class BoundRules:
    """`Rules` for a plug-in's calculators: parameter -> bound attribute -> current fact."""

    def __init__(
        self,
        session: Session,
        onto: Ontology,
        plugin: str,
        today: date | None = None,
        as_of: date | None = None,
        known_at: datetime | None = None,
    ) -> None:
        self.session, self.onto, self.plugin, self.today = session, onto, plugin, today
        self.as_of, self.known_at = as_of, known_at
        self.used: list[RuleValue] = []
        self.bindings = {b.param: b.attribute_key for b in kb.get_bindings(session, plugin)}

    def get(
        self, topic: str, parameter: str, client: str | None = None, as_of: date | None = None
    ) -> RuleValue:
        param = f"{topic}.{parameter}"
        attr = self.bindings.get(param)
        if not attr:
            raise RuleNotFound(
                f"plug-in {self.plugin}: parameter {param} is not bound to the "
                "schema (see Setup → Plug-in bindings)"
            )
        rv = get_rule(
            self.session,
            self.onto,
            topic,
            parameter,
            client=client,
            as_of=as_of or self.as_of,
            known_at=self.known_at,
            today=self.today,
            attribute=attr,
        )
        self.used.append(rv)
        return rv
