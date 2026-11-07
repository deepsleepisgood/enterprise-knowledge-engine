"""Schema evolution (BUILD_PLAN Phase 2a, "new attributes found later are proposed").

After extraction, facts the extractor could not place in the schema carry `other:<name>`. This
step closes that gap without re-extracting anything:

1. Group: the live `other:*` facts are grouped by their proposed name, and names that mean the
   same thing (embedding similarity, compatible value type) are merged into one group.
2. Map: each group is compared with the existing attributes (embedding plus word overlap, value
   type must be compatible). A clear match maps directly; an ambiguous one is confirmed by
   MODEL_FAST (cached). Mapped groups become `remaps`.
3. Propose: groups that match nothing go to one MODEL_SMART call (cached) that names a new
   attribute for each, under an existing topic or a new one, or marks it as not a reusable
   attribute (a one-off statement). Version-, time-, client- or document-named keys are refused.
4. A new schema version is saved with the new topics and attributes. When it is frozen (by the
   owner on the Setup page, or `auto_freeze` in builds and tests), `apply` re-keys the facts:
   each one is retracted and re-inserted under its new attribute (history is kept), and the
   affected groups go through authority resolution in the same transaction.
Nothing here names a domain: the same loop serves any tenant.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.graph.induce import _TEMPORAL
from app.graph.ontology import Attribute, Ontology, Topic, ValueType
from app.plugins.bindings import COMPATIBLE, _attr_text, _words
from app.store import entities as ent
from app.store import facts as fstore
from app.store import kb
from app.store.base import advisory_lock, tenant, utcnow

PROMPT_VERSION = "evolve-v1"
OTHER = "other:"
CLUSTER_SIM = 0.88  # two proposed names are the same attribute
MAP_HIGH = 0.90  # map to an existing attribute without asking
MAP_LOW = 0.72  # below this, an existing attribute is not even a candidate
PROPOSE_BATCH = 40
_SCOPE_WORDS = re.compile(r"(^|_)(general|default_scope|all_clients|client_specific)(_|$)")

Embed = Callable[[list[str]], list[list[float]]]


# ---------------------------------------------------------------- data shapes


@dataclass
class Group:
    keys: list[str]
    facts: list[fstore.FactRow]
    value_type: str

    @property
    def name(self) -> str:
        return self.keys[0].removeprefix(OTHER)

    def text(self) -> str:
        """What the group is about: its names plus up to three example statements."""
        names = " ".join(k.removeprefix(OTHER).replace("_", " ") for k in self.keys)
        examples = " ".join(f.statement for f in self.facts[:3])
        return f"{names}. {examples}"


@dataclass
class Decision:
    keys: list[str]
    facts: int
    action: str  # map | new | skip
    attribute: str | None
    method: str
    confidence: float = 0.0


@dataclass
class EvolveReport:
    from_version: int | None = None
    to_version: int | None = None
    frozen: bool = False
    groups: int = 0
    mapped: int = 0
    proposed: int = 0
    skipped: int = 0
    rekeyed: int = 0
    kb_version: int | None = None
    decisions: list[Decision] = field(default_factory=list)

    def remaps(self) -> dict[str, str]:
        return {k: d.attribute for d in self.decisions if d.attribute for k in d.keys}


class _Pick(BaseModel):
    choice: int = Field(description="Number of the attribute that holds these facts, or 0")
    reason: str


class _NewAttribute(BaseModel):
    group: int = Field(description="The group number")
    keep: bool = Field(
        description="False if the group is not a reusable attribute: a one-off "
        "statement, document metadata, or text with no value to look up"
    )
    topic: str = Field("", description="An existing topic key, or a new snake_case topic key")
    topic_label: str = Field("", description="Label for a new topic")
    parameter: str = Field("", description="snake_case parameter name within the topic")
    label: str = ""
    description: str = ""
    value_type: ValueType = "text"
    unit: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    risk: str = Field("low", description="high, medium or low (for a new topic)")


class _Proposals(BaseModel):
    attributes: list[_NewAttribute]


PROPOSE_SYSTEM = """You extend the schema of an organisation's knowledge graph.
Each group below is a set of facts the extractor could not place in the schema. For each group,
either name one reusable attribute for it or set keep=false.
- Prefer an existing topic; create a new topic only for a subject the schema does not cover.
- Attribute keys are "<topic>.<parameter>" in snake_case; one attribute per independently
  changeable value.
- Never name versions or time (old, new, previous, v2), one client, site or department, or one
  document: the graph records time, scope and source for every fact.
- keep=false for document metadata (a version, an effective date, a status, a disclaimer) and for
  statements with no value anyone would look up."""


# ---------------------------------------------------------------- helpers


def _value_type(facts: list[fstore.FactRow]) -> str:
    types = Counter(str((f.value or {}).get("type") or "text") for f in facts)
    return types.most_common(1)[0][0]


def _compatible(a: str, b: str) -> bool:
    return b in COMPATIBLE.get(a, {a}) or a in COMPATIBLE.get(b, {b})


def _cos(a: list[float], b: list[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


def _overlap(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / max(len(wa), 1)


def collect(session: Session) -> dict[str, list[fstore.FactRow]]:
    out: dict[str, list[fstore.FactRow]] = defaultdict(list)
    for r in fstore.live_with_attribute_prefix(session, OTHER):
        out[r.attribute].append(r)
    return dict(out)


def group(by_key: dict[str, list[fstore.FactRow]], embed_fn: Embed | None) -> list[Group]:
    """Greedy clustering, most frequent names first, so groups are stable across runs."""
    keys = sorted(by_key, key=lambda k: (-len(by_key[k]), k))
    singles = [Group([k], by_key[k], _value_type(by_key[k])) for k in keys]
    if embed_fn is None or len(singles) < 2:
        return singles
    vecs = embed_fn([g.text() for g in singles])
    groups: list[Group] = []
    centres: list[list[float]] = []
    for g, v in zip(singles, vecs, strict=True):
        for i, c in enumerate(centres):
            if _compatible(g.value_type, groups[i].value_type) and _cos(v, c) >= CLUSTER_SIM:
                groups[i].keys += g.keys
                groups[i].facts += g.facts
                break
        else:
            groups.append(g)
            centres.append(v)
    return groups


def _candidates(
    g: Group, onto: Ontology, gvec: list[float] | None, avecs: list[list[float]] | None
) -> list[tuple[float, Attribute]]:
    scored = []
    for i, a in enumerate(onto.attributes):
        if not _compatible(g.value_type, a.value_type):
            continue
        words = _overlap(g.text(), _attr_text(a, onto))
        cos = _cos(gvec, avecs[i]) if gvec is not None and avecs is not None else 0.0
        score = 0.7 * cos + 0.3 * words if gvec is not None else words
        if score >= MAP_LOW * (1.0 if gvec is not None else 0.5):
            scored.append((score, a))
    return sorted(scored, key=lambda t: -t[0])[:5]


def _clean_key(topic: str, parameter: str) -> tuple[str, str] | None:
    t = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    p = re.sub(r"[^a-z0-9]+", "_", parameter.lower()).strip("_")
    p = re.sub(r"_+", "_", _SCOPE_WORDS.sub("_", p)).strip("_")
    if not t or not p or _TEMPORAL.search(p) or t == "other":
        return None
    return t, p


# ---------------------------------------------------------------- the loop


def evolve(
    session: Session,
    onto: Ontology,
    from_version: int,
    mode: str,
    structured_fn: Callable[..., Any] | None = None,
    embed_fn: Embed | None = None,
) -> tuple[Ontology | None, EvolveReport]:
    """Decide what to do with the `other:*` facts and draft the next schema version.

    Returns (new ontology or None when nothing changes, report). Nothing is re-keyed here; see
    `apply`. The new version is saved as a draft with a `schema` review item.
    """
    rep = EvolveReport(from_version=from_version)
    groups = group(collect(session), embed_fn)
    rep.groups = len(groups)
    if not groups:
        return None, rep

    avecs = (
        embed_fn([_attr_text(a, onto) for a in onto.attributes])
        if (embed_fn is not None and onto.attributes)
        else None
    )
    gvecs = embed_fn([g.text() for g in groups]) if embed_fn is not None else [None] * len(groups)
    unplaced: list[Group] = []
    for g, gv in zip(groups, gvecs, strict=True):
        cands = _candidates(g, onto, gv, avecs)
        if cands and cands[0][0] >= MAP_HIGH:
            rep.decisions.append(
                Decision(
                    g.keys, len(g.facts), "map", cands[0][1].key, "embedding", round(cands[0][0], 2)
                )
            )
            continue
        if cands and structured_fn is not None:
            lines = "\n".join(
                f"{n}. {a.key} [{a.value_type}] {a.label}: {a.description}"
                for n, (_, a) in enumerate(cands, 1)
            )
            examples = "\n".join(f"- {f.statement}" for f in g.facts[:5])
            pick: _Pick = structured_fn(
                f"Facts the extractor filed under '{g.name}' (type {g.value_type}):\n{examples}\n\n"
                f"Existing attributes:\n{lines}\n\n"
                "Which attribute holds exactly these facts? Answer 0 if none does.",
                _Pick,
                model="fast",
                prompt_version=PROMPT_VERSION,
                max_tokens=2048,
            )
            if 1 <= pick.choice <= len(cands):
                rep.decisions.append(
                    Decision(
                        g.keys,
                        len(g.facts),
                        "map",
                        cands[pick.choice - 1][1].key,
                        "embedding + LLM",
                        0.8,
                    )
                )
                continue
        unplaced.append(g)

    new_topics: dict[str, Topic] = {}
    new_attrs: dict[str, Attribute] = {}
    if unplaced and structured_fn is not None:
        topic_lines = "\n".join(f"- {t.key}: {t.label}" for t in onto.topics)
        for start in range(0, len(unplaced), PROPOSE_BATCH):
            batch = unplaced[start : start + PROPOSE_BATCH]
            body = "\n\n".join(
                f"Group {i}: '{g.name}' ({g.value_type}, {len(g.facts)} facts)\n"
                + "\n".join(f"- {f.statement}" for f in g.facts[:4])
                for i, g in enumerate(batch, 1)
            )
            out: _Proposals = structured_fn(
                f"Existing topics:\n{topic_lines}\n\nGroups:\n{body}",
                _Proposals,
                system=PROPOSE_SYSTEM,
                model="smart",
                prompt_version=PROMPT_VERSION,
                max_tokens=16384,
            )
            by_group = {p.group: p for p in out.attributes}
            for i, g in enumerate(batch, 1):
                p = by_group.get(i)
                cleaned = _clean_key(p.topic, p.parameter) if p is not None and p.keep else None
                if p is None or cleaned is None:
                    rep.decisions.append(
                        Decision(
                            g.keys,
                            len(g.facts),
                            "skip",
                            None,
                            "not a reusable attribute" if p else "no answer",
                        )
                    )
                    continue
                t, param = cleaned
                key = f"{t}.{param}"
                if onto.attribute(key) is None and key not in new_attrs:
                    new_attrs[key] = Attribute(
                        key=key,
                        topic=t,
                        label=p.label or param.replace("_", " "),
                        description=p.description,
                        value_type=p.value_type,
                        unit=p.unit,
                        synonyms=[g.name.replace("_", " "), *p.synonyms][:8],
                    )
                if onto.topic(t) is None and t not in new_topics:
                    risk = p.risk if p.risk in ("high", "medium", "low") else "low"
                    new_topics[t] = Topic(
                        key=t, label=p.topic_label or t.replace("_", " ").capitalize(), risk=risk
                    )  # type: ignore[arg-type]
                rep.decisions.append(Decision(g.keys, len(g.facts), "new", key, "proposed", 0.7))
    else:
        for g in unplaced:
            rep.decisions.append(Decision(g.keys, len(g.facts), "skip", None, "no LLM"))

    rep.mapped = sum(1 for d in rep.decisions if d.action == "map")
    rep.proposed = len(new_attrs)
    rep.skipped = sum(1 for d in rep.decisions if d.action == "skip")
    if not rep.remaps():
        return None, rep
    new = onto.model_copy(deep=True)
    new.topics += list(new_topics.values())
    new.attributes += list(new_attrs.values())
    version = kb.save_schema(session, new.model_dump(), mode)
    rep.to_version = version
    kb.add_review_item(
        session,
        "schema",
        {
            "summary": f"Schema v{version}: {rep.proposed} new attributes, "
            f"{len(new_topics)} new topics; {rep.mapped} groups of unplaced facts "
            f"map to existing attributes",
            "from_version": from_version,
            "version": version,
            "new_topics": [t.key for t in new_topics.values()],
            "new_attributes": list(new_attrs),
            "remaps": rep.remaps(),
            "skipped": [d.keys for d in rep.decisions if d.action == "skip"],
        },
    )
    return new, rep


def apply(
    session: Session,
    onto: Ontology,
    remaps: dict[str, str],
    compare: Any,
    resolver: Any,
    summary: str = "schema evolution",
) -> tuple[int, int | None]:
    """Re-key `other:*` facts to their new attributes and re-resolve the groups they join.

    Runs in the caller's transaction (CLAUDE.md rule 7). Returns (facts re-keyed, kb version).
    """
    from app.graph.write import publish, topic_entity

    advisory_lock(session, f"graph-write:{tenant()}")
    now = utcnow()
    groups: set[tuple[str, str]] = set()
    moved = 0
    for old_key, new_key in sorted(remaps.items()):
        attr = onto.attribute(new_key)
        if attr is None:
            continue
        topic_id = topic_entity(resolver, onto, attr.topic)
        for r in fstore.live_with_attribute_prefix(session, old_key):
            if r.attribute != old_key:
                continue  # prefix match on a longer key
            subject = r.subject_id
            row = ent.get(session, subject)
            if row is not None and row.type == "topic":
                subject = topic_id  # topic-level facts move to their new topic
            fstore.revise(
                session,
                r.id,
                at=now,
                attribute=new_key,
                subject_id=subject,
                meta={**(r.meta or {}), "evolved_from": old_key, "topic": attr.topic},
            )
            groups.add((subject, new_key))
            moved += 1
    if not moved:
        return 0, None
    rep = publish(session, [], [], onto, compare, resolver, summary=summary, extra_groups=groups)
    version = rep.kb_version
    if version is None:  # resolution unchanged, but facts moved: still a published change
        version = kb.bump_kb_version(session, summary)
        kb.record_change(session, version, f"{summary}: {moved} facts re-keyed")
    return moved, version
