"""Schema induction (BUILD_PLAN Phase 2a): propose an ontology from a sample of the corpus.

1. Sample leaf passages stratified by source (records and parent passages excluded).
2. Per batch, MODEL_SMART proposes topics, attributes (one per independently changeable value),
   entity types and unit multipliers.
3. A consolidation call merges the candidates and proposes the source ranking, risk levels and
   sender authority from the document list.
The result is saved as a draft schema; the owner edits and freezes it (or `auto_freeze`).
With SCHEMA_MODE=baseline the first plug-in's hand-written schema is used instead.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import BaseModel, Field

from app.graph.ontology import Attribute, EntityType, Ontology, SenderAuthority, SourceRank, Topic

PROMPT_VERSION = "induce-v2"
PER_SOURCE = 14
PASSAGE_CHARS = 1400
BATCH_CHARS = 16000
SKIP_KINDS = {"record", "preamble"}


class _Unit(BaseModel):
    word: str
    multiplier: float


class _Candidates(BaseModel):
    entity_types: list[EntityType]
    topics: list[Topic]
    attributes: list[Attribute]
    units: list[_Unit] = Field(
        default_factory=list,
        description="Words for multiples of a base unit used in the text, with the multiplier",
    )
    base_currency: str | None = None


class _Final(BaseModel):
    entity_types: list[EntityType]
    topics: list[Topic]
    attributes: list[Attribute]
    source_ranking: list[SourceRank]
    sender_authority: list[SenderAuthority]
    scope_keys: list[str]


BATCH_SYSTEM = """You design the schema of a knowledge graph built from one organisation's documents.
From the passages given, list:
- topics: each area the documents set rules or facts about (snake_case key, label, synonyms
  people use, including codes and abbreviations), with risk high for money movement, bank or
  payment details, approvals, tax or legal matters; medium for compliance; else low;
- attributes: for each topic, one attribute per independently changeable value a rule or fact
  sets. Key "<topic>.<parameter>" in snake_case. If a rule combines two numbers (a percentage
  and a cap), they are two attributes. If a table gives a value per category, make one
  attribute per category. Give value_type (percentage, money, days, number, date, enum, text,
  list, boolean) and unit;
- entity_types: kinds of named things the documents talk about;
- units: words the text uses for multiples of a unit, with their multiplier;
- base_currency: the currency code money amounts are in, if any.
Use only what the passages support. Be specific: a calculator should be able to read each
numeric attribute on its own.
The graph records time, scope and source for every fact, so the schema must not:
- name versions or time in topics or attributes (no "old_", "new_", "previous", "v3", "current"):
  an earlier and a later value of the same rule share one attribute;
- make topics or attributes for one client, customer, site or department: a rule that a memo
  changes for one client uses the general rule's attribute (the fact is scoped to that client);
- make a topic per document (a memo, an FAQ): topics are subjects, not sources."""

FINAL_SYSTEM = """You merge candidate schema fragments into one schema for a knowledge graph.
- Merge topics and attributes that mean the same thing (one topic per subject, even if fragments
  name it differently); keep the most specific keys; keep every distinct numeric attribute; union
  the synonyms. Attribute keys must start with their topic key.
- Remove any topic or attribute named after a version, a time ("old", "previous", "v3"), one
  client, site or department, or one document: fold its values into the general attribute.
- Always include an entity type "topic" and the entity types the fragments propose.
- source_ranking: rank every document type listed (1 = most authoritative). Controlled,
  current, owner-approved documents rank above training material, which ranks above informal
  exports and messages. A document limited to one client overrides the general rules for that
  client only, so it may rank first. Mark interview and observation records practice=true.
- sender_authority: from the document owners, who may change rules on which topics, for which
  client scope ("all" when not limited).
- scope_keys: the dimensions rules are scoped by (always include "client")."""


def sample(passages: list[Any]) -> list[Any]:
    by_source: dict[str, list[Any]] = defaultdict(list)
    for p in passages:
        if p.segment_kind in SKIP_KINDS or not (p.meta or {}).get("leaf", True):
            continue
        by_source[p.source_id].append(p)
    out = []
    for ps in by_source.values():
        if len(ps) <= PER_SOURCE:
            out += ps
        else:  # spread over the document
            step = len(ps) / PER_SOURCE
            out += [ps[int(i * step)] for i in range(PER_SOURCE)]
    return out


def batches(passages: list[Any]) -> list[list[Any]]:
    out, cur, size = [], [], 0
    for p in passages:
        n = min(len(p.text), PASSAGE_CHARS) + len(p.context_header)
        if cur and size + n > BATCH_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += n
    if cur:
        out.append(cur)
    return out


def _batch_prompt(batch: list[Any]) -> str:
    return "\n\n".join(f"[{p.context_header}]\n{p.text[:PASSAGE_CHARS]}" for p in batch)


def induce(
    passages: list[Any],
    sources: list[Any],
    structured_fn: Callable[..., Any] | None = None,
    workers: int = 4,
) -> tuple[Ontology, list[str]]:
    """Returns (ontology, ids of the sampled passages)."""
    if structured_fn is None:
        from app.core.llm import structured

        structured_fn = structured
    picked = sample(passages)

    def run(batch: list[Any]) -> _Candidates:
        return structured_fn(
            _batch_prompt(batch),
            _Candidates,
            system=BATCH_SYSTEM,
            model="smart",
            prompt_version=PROMPT_VERSION,
            max_tokens=16384,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        cands = list(pool.map(run, batches(picked)))

    units: dict[str, float] = {}
    currency = None
    for c in cands:
        units.update({u.word.lower(): u.multiplier for u in c.units if u.multiplier > 0})
        currency = currency or c.base_currency
    docs = sorted(
        {(s.doc_type, s.status, s.short_label, s.owner or "", s.client_scope) for s in sources}
    )
    doc_lines = "\n".join(
        f"- type {t}, status {st}, '{lbl}', owner {own or 'unknown'}, scope {sc}"
        for t, st, lbl, own, sc in docs
    )
    fragments = json.dumps(
        [c.model_dump(include={"entity_types", "topics", "attributes"}) for c in cands],
        ensure_ascii=False,
    )
    final: _Final = structured_fn(
        f"Documents in the knowledge base:\n{doc_lines}\n\nCandidate fragments:\n{fragments}",
        _Final,
        system=FINAL_SYSTEM,
        model="smart",
        prompt_version=PROMPT_VERSION,
        max_tokens=32768,
    )
    onto = Ontology(
        name="induced",
        base_currency=currency,
        units=units,
        entity_types=_dedupe(final.entity_types, "name", EntityType(name="topic")),
        topics=_dedupe(final.topics, "key"),
        attributes=_valid_attributes(final.attributes, {t.key for t in final.topics}),
        source_ranking=_complete_ranking(final.source_ranking, {s.doc_type for s in sources}),
        scope_keys=sorted({"client", *final.scope_keys}),
        sender_authority=final.sender_authority,
    )
    return onto, [p.id for p in picked]


def _dedupe(items: list[Any], key: str, must: Any | None = None) -> list[Any]:
    seen: dict[str, Any] = {}
    for it in [*([must] if must else []), *items]:
        seen.setdefault(getattr(it, key).strip().lower(), it)
    return list(seen.values())


# Attribute names that encode time or version: the graph's validity intervals hold that.
_TEMPORAL = re.compile(r"(^|_)(old|new|previous|prior|legacy|former|current|v\d+\w*)(_|$)")


def _valid_attributes(attrs: list[Attribute], topics: set[str]) -> list[Attribute]:
    out: dict[str, Attribute] = {}
    for a in attrs:
        if _TEMPORAL.search(a.key.split(".", 1)[-1]):
            continue
        topic = a.topic if a.topic in topics else a.key.split(".", 1)[0]
        if topic not in topics:
            continue
        key = a.key if a.key.startswith(f"{topic}.") else f"{topic}.{a.key.split('.')[-1]}"
        out.setdefault(key, a.model_copy(update={"key": key, "topic": topic}))
    return list(out.values())


def _complete_ranking(ranking: list[SourceRank], present: set[str]) -> list[SourceRank]:
    have = {r.doc_type for r in ranking}
    worst = max((r.rank for r in ranking), default=1)
    extra = [
        SourceRank(doc_type=t, rank=worst + 1, reason="not ranked by induction")
        for t in sorted(present - have)
    ]
    return sorted([*ranking, *extra], key=lambda r: r.rank)


def coverage(induced: Ontology, baseline: Ontology) -> dict[str, Any]:
    """Share of baseline topics and attributes the induced schema has under some name."""

    def names(o: Ontology, a: Attribute) -> set[str]:
        t = o.topic(a.topic)
        return {
            a.key,
            a.label.lower(),
            *(s.lower() for s in a.synonyms),
            *((s.lower() for s in t.synonyms) if t else ()),
        }

    ind_topic_names = {n.lower() for t in induced.topics for n in [t.key, t.label, *t.synonyms]}
    topics_hit = [
        t.key
        for t in baseline.topics
        if {n.lower() for n in [t.key, t.label, *t.synonyms]} & ind_topic_names
    ]
    return {
        "topics": f"{len(topics_hit)}/{len(baseline.topics)}",
        "topics_missing": sorted({t.key for t in baseline.topics} - set(topics_hit)),
        "attributes_induced": len(induced.attributes),
        "attributes_baseline": len(baseline.attributes),
        "_names": names,
    }
