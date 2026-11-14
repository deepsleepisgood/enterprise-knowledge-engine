"""Answer card assembly: rule text with [n] markers, citations, older sources, tip, routing.

The card shape is the API contract the UI renders (web/lib/types.ts AnswerCard). Keep field
names stable.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.answer.generate import GenOut
from app.answer.verify import best_sentence, find_quote, numbers
from app.graph.ontology import Ontology
from app.graph.rules import CURRENT, IN_FORCE_THEN
from app.store import facts as fstore
from app.store import search
from app.store.facts import FactRow
from app.store.search import PassageHit

PROCESS_OWNER = "Process owner"
OWNER_VIEWERS = {"owner", "eval"}


def citation(n: int, p: PassageHit, quote: str) -> dict[str, Any]:
    return {
        "n": n,
        "passage_id": p.id,
        "file": p.file,
        "short_label": p.label,
        "locator": p.locator,
        "section_title": p.section_title or "",
        "doc_type": p.doc_type,
        "status": p.source_status,
        "quote": quote,
    }


def assemble(
    gen: GenOut, evidence: dict[str, PassageHit]
) -> tuple[str, list[dict[str, Any]], list[str], list[str]]:
    """(rule text with [n] markers, citations, cited passage ids, quote problems)."""
    number: dict[str, int] = {}
    parts = []
    for s in gen.sentences:
        marks = []
        for src in s.sources:
            if src not in number:
                number[src] = len(number) + 1
            marks.append(f"[{number[src]}]")
        text = s.text.rstrip()
        parts.append(f"{text} {''.join(dict.fromkeys(marks))}")
    quotes: dict[str, str] = {}
    for q in gen.quotes:
        quotes.setdefault(q.source, q.quote)
    problems, cites = [], []
    for src, n in number.items():
        p = evidence[src]
        given = quotes.get(src)
        if given:
            found = find_quote(given, p.text)
            if found is None:
                problems.append(f"the quote given for {src} does not occur in that passage")
                found = best_sentence(p.text, given)
        else:
            claim = " ".join(s.text for s in gen.sentences if src in s.sources)
            found = best_sentence(p.text, claim)
        cites.append(citation(n, p, found))
    return " ".join(parts).strip(), cites, [evidence[s].id for s in number], problems


def attach_number_sources(gen: GenOut, evidence: dict[str, PassageHit], given: list[str]) -> int:
    """Cite the evidence a sentence's number comes from when the model left it out.

    For each number in a sentence that is not in its cited passages or in `given` (the question,
    calculator output), add the evidence passage that contains it and shares the most words
    with the sentence. Evidence is already limited to sources in force on the day asked, and
    the not-in-force check still runs afterwards. Returns the number of sources added."""

    def words(t: str) -> set[str]:
        return set(re.findall(r"[a-z]{3,}", t.lower()))

    added = 0
    base = numbers(" ".join(given))
    for s in gen.sentences:
        mine = [evidence[x] for x in s.sources if x in evidence]
        have = base | numbers(
            " ".join(f"{h.text} {h.label} {h.locator} {h.section_title or ''}" for h in mine)
        )
        for n in sorted(numbers(s.text) - have):
            pool = [
                (len(words(h.text) & words(s.text)), key)
                for key, h in evidence.items()
                if key not in s.sources and n in numbers(h.text)
            ]
            if pool:
                s.sources.append(max(pool)[1])
                added += 1
    return added


def _scoped(facts: list[FactRow], client: str | None) -> list[FactRow]:
    out = []
    for f in facts:
        c = (f.scope or {}).get("client")
        if not c or c == "all" or client is None or c == client:
            out.append(f)
    return out


def force_split(
    session: Session,
    attributes: list[str],
    client: str | None,
    as_of: date | None,
    today: date,
    known_at: datetime | None = None,
) -> tuple[list[FactRow], list[FactRow]]:
    """(in force on the day asked, not in force) for these attributes, rules only, as the engine
    knew them at `known_at` (default: now).

    "Not in force" is anchored: only versions of something that is in force now (same subject
    and attribute), so list-like attributes (one fact per code) never look like replacements.
    Pending facts are listed as not in force (an unconfirmed older statement, such as a stale
    FAQ answer, is shown as outdated; it never answers).
    """
    if not attributes:
        return [], []
    day = as_of or today
    statuses = IN_FORCE_THEN if as_of else CURRENT
    now = [
        f
        for f in fstore.get_facts(
            session, attribute=attributes, valid_on=day, known_at=known_at, statuses=statuses
        )
        if f.kind != "practice"
    ]
    everything = [
        f
        for f in fstore.get_facts(
            session,
            attribute=attributes,
            known_at=known_at,
            statuses=["current", "superseded", "overridden", "provisional", "pending"],
        )
        if f.kind != "practice"
    ]
    now = _scoped(now, client)
    ids = {f.id for f in now}
    anchors = {(f.subject_id, f.attribute) for f in now}
    older = [
        f
        for f in _scoped(everything, client)
        if f.id not in ids and (f.subject_id, f.attribute) in anchors
    ]
    return now, older


def _value_text(f: FactRow) -> str:
    return str(f.value.get("text") or f.statement)


def older_sources(
    session: Session,
    onto: Ontology,
    in_force: list[FactRow],
    not_in_force: list[FactRow],
    as_of: date | None,
    today: date,
    cited_keys: dict[tuple[str, str], int] | None = None,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Older or overridden values for the attributes the answer used, with what replaced them.

    Only for what the answer is about: (subject, attribute) pairs with a fact in a cited passage
    (`cited_keys`, value = position of that passage), earliest citation first. A pair with
    several different values in force for one scope is a list (one fact per item), not a value
    that replaced another, and is skipped.
    """
    day = as_of or today
    keys = cited_keys or {}

    def now_for(f: FactRow) -> list[FactRow]:
        return [x for x in in_force if x.attribute == f.attribute and x.subject_id == f.subject_id]

    cands = sorted(
        (
            f
            for f in not_in_force
            if f.status in ("superseded", "overridden", "pending")
            and (f.valid_from is None or f.valid_from.date() <= day)
            and (f.subject_id, f.attribute) in keys
        ),
        key=lambda f: (keys[(f.subject_id, f.attribute)], f.attribute, f.id),
    )
    hits = search.hydrate(session, [f.passage_id for f in [*cands, *in_force] if f.passage_id])
    out, seen = [], set()
    for old in cands:
        scope = (old.scope or {}).get("client")
        now = [x for x in now_for(old) if (x.scope or {}).get("client") == scope] or now_for(old)
        if not now or len({_value_text(x).lower() for x in now}) > 1:
            continue
        cur = min(now, key=lambda f: f.authority_rank)
        if old.source_id and old.source_id == cur.source_id:
            continue  # a document does not supersede itself
        if old.status == "pending" and not (
            old.valid_from and cur.valid_from and old.valid_from < cur.valid_from
        ):
            continue  # an unconfirmed statement is shown only when it predates the rule
        if _value_text(old).strip().lower() == _value_text(cur).strip().lower():
            continue
        if len(old.value.get("items") or []) > 2 or _value_text(old).count(",") >= 2:
            continue  # a list of items (e.g. codes) is not one older value
        if old.value.get("number") is not None and old.value.get("number") == cur.value.get(
            "number"
        ):
            continue
        key = (old.attribute, _value_text(old).lower(), old.source_label)
        if key in seen:
            continue
        seen.add(key)
        attr = onto.attribute(old.attribute)
        topic = onto.topic(attr.topic) if attr else None
        p = hits.get(old.passage_id or "")
        replaced_on = cur.valid_from.date() if cur.valid_from else None
        if old.valid_to is not None:
            replaced_on = old.valid_to.date()
        out.append(
            {
                "topic": (topic.label if topic else None)
                or (attr.label if attr else old.attribute),
                "current_value": _value_text(cur),
                "older_value": _value_text(old),
                "file": p.file if p else (old.source_label or ""),
                "locator": p.label if p else (old.locator or ""),
                "superseded_by": hits[cur.passage_id].label
                if cur.passage_id in hits
                else f"{cur.source_label or ''} {cur.locator or ''}".strip(),
                "superseded_on": replaced_on.isoformat() if replaced_on else "",
            }
        )
        if len(out) >= limit:
            break
    return out


def conflicting_sources(
    session: Session, cited_fact_ids: list[int], limit: int = 4
) -> list[dict[str, Any]]:
    """Sources the conflict scan found disagreeing with a fact the answer cites, where the cited
    fact holds: an outdated FAQ that states another rule under another name, which the
    same-attribute 'older sources' line cannot see. Same shape as `older_sources`."""
    from sqlalchemy import or_, select

    from app.store.base import tenant
    from app.store.models import Conflict

    if not cited_fact_ids:
        return []
    rows = session.scalars(
        select(Conflict).where(
            Conflict.tenant_id == tenant(),
            Conflict.status == "open",
            Conflict.kind == "value",
            Conflict.authoritative_fact.in_(cited_fact_ids),
            or_(Conflict.fact_a.in_(cited_fact_ids), Conflict.fact_b.in_(cited_fact_ids)),
        )
    ).all()
    pairs = [
        (c.authoritative_fact, c.fact_b if c.fact_a == c.authoritative_fact else c.fact_a, c)
        for c in rows
    ]
    facts = fstore.by_ids(session, sorted({i for a, b, _ in pairs for i in (a, b)}))
    hits = search.hydrate(session, [f.passage_id for f in facts.values() if f.passage_id])
    out, seen = [], set()
    for a, b, c in pairs:
        cur, old = facts.get(a), facts.get(b)
        if cur is None or old is None:
            continue
        p, q = hits.get(old.passage_id or ""), hits.get(cur.passage_id or "")
        key = (p.file if p else old.source_label, _value_text(old).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "topic": cur.attribute,
                "current_value": _value_text(cur),
                "older_value": _value_text(old),
                "file": p.file if p else (old.source_label or ""),
                "locator": p.label if p else (old.locator or ""),
                "superseded_by": q.label if q else (cur.source_label or ""),
                "superseded_on": cur.valid_from.date().isoformat() if cur.valid_from else "",
                "reason": c.reason or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def superseded_since(in_force: list[FactRow], cited_fact_ids: set[int], today: date) -> str | None:
    """For an as_of answer: when the rule in force then was replaced (if it was)."""
    ends = [
        f.valid_to.date()
        for f in in_force
        if f.id in cited_fact_ids and f.valid_to is not None and f.valid_to.date() <= today
    ]
    return min(ends).isoformat() if ends else None


def _restates_rule(session: Session, tip: FactRow, day: date) -> bool:
    """A practice fact with the same number as the rule in force says nothing new."""
    n = tip.value.get("number")
    if n is None or tip.attribute.startswith("other:"):
        return False
    rules = fstore.get_facts(session, attribute=tip.attribute, valid_on=day, statuses=CURRENT)
    return any(r.kind != "practice" and r.value.get("number") == n for r in rules)


TIP_MIN_SIM = 0.62  # an unused note on the answer's topic must be this close to the question
TIP_OFF_TOPIC_SIM = 0.72  # ... and one on no topic the answer cites, this close
TIP_USED_MIN_SIM = 0.55  # a note from a cited passage must match what the answer said from it


def _topic(attribute: str) -> str | None:
    return None if attribute.startswith("other:") else attribute.split(".", 1)[0]


def expert_tip(
    session: Session,
    day: date,
    *,
    cited: list[str],
    named: list[FactRow],
    tips: list[tuple[FactRow, float]],
    ranked_passages: list[str],
    question_vec: list[float] | None,
    practice_types: set[str] | None = None,
    row_origin: str = "",
    used_vecs: dict[str, list[float]] | None = None,
    answer_topics: set[str] | None = None,
) -> dict[str, Any] | None:
    """The practice note shown beside the answer: know-how that says something the rule does
    not, from a source type the schema marks as practice (interviews, observations, data rows).

    A note the answer itself used comes first: from a cited practice passage, the note closest
    to what the answer's sentences said from that passage (`used_vecs`, passage id -> their
    embedding), since one interview answer often covers several topics. A note about one named
    party read from a data row is shown only then. Any other note must be about the question:
    on a topic the answer's rules are about (`answer_topics`) and at least TIP_MIN_SIM similar,
    or at least TIP_OFF_TOPIC_SIM similar. Without `used_vecs`, a cited note is judged by its
    similarity to the question like the rest."""
    used_vecs = used_vecs or {}
    topics = answer_topics or set()
    cands: dict[int, FactRow] = {f.id: f for f in named}
    for f, _ in tips:
        cands.setdefault(f.id, f)
    for f in fstore.live_for_passages(session, list(dict.fromkeys([*cited, *ranked_passages]))):
        if f.kind == "practice":
            cands.setdefault(f.id, f)
    useful = [f for f in cands.values() if f.passage_id and not _restates_rule(session, f, day)]
    hits = search.hydrate(session, [f.passage_id for f in useful if f.passage_id])
    useful = [
        f
        for f in useful
        if f.passage_id in hits
        and (
            not practice_types
            or hits[f.passage_id].doc_type in practice_types
            or hits[f.passage_id].segment_kind == "record"  # a note in a data row
        )
    ]
    sims = fstore.similarity(session, [f.id for f in useful], question_vec) if question_vec else {}
    used: dict[int, float] = {}
    for pid, vec in used_vecs.items():
        ids = [f.id for f in useful if f.passage_id == pid]
        used.update(fstore.similarity(session, ids, vec) if ids and vec else {})
    pos = {pid: i for i, pid in enumerate(cited)}
    named_ids = {f.id for f in named}

    def entity_note(f: FactRow) -> bool:
        return f.id in named_ids or bool(row_origin and f.origin_key.startswith(row_origin))

    def on_point(f: FactRow) -> bool:
        sim = sims.get(f.id, 0.0)
        return sim >= TIP_OFF_TOPIC_SIM or (_topic(f.attribute) in topics and sim >= TIP_MIN_SIM)

    def score(f: FactRow) -> float:
        return used.get(f.id, sims.get(f.id, 0.0))

    def shown(f: FactRow) -> bool:
        if f.passage_id in pos and entity_note(f):
            return True  # gated as on point before it became evidence (retrieve)
        if f.passage_id in pos and f.id in used:
            return used[f.id] >= TIP_USED_MIN_SIM
        return not entity_note(f) and on_point(f)

    pick = [f for f in useful if shown(f)]
    pick.sort(key=lambda f: (pos.get(f.passage_id or "", len(pos)), -score(f)))
    if not pick:
        return None
    f = pick[0]
    p = hits[f.passage_id or ""]
    author = p.speaker or (f.meta or {}).get("author") or p.source_label
    when = p.dated.isoformat() if p.dated else ""
    quote = best_sentence(p.text, f.statement)
    return {
        "text": f.statement,
        "author": author,
        "date": when,
        "citation": citation(0, p, quote),
        "approved_by": (f.meta or {}).get("approved_by"),
    }


def route_to(role_key: str | None, roles: dict[str, dict[str, Any]], reason: str) -> dict[str, str]:
    if role_key and role_key in roles:
        return {"role": roles[role_key].get("name", role_key), "reason": reason}
    for wanted in ("process_gap", "conflict"):
        for r in roles.values():
            if wanted in (r.get("default_for") or []):
                return {"role": r.get("name", r["key"]), "reason": reason}
    return {"role": PROCESS_OWNER, "reason": reason}


def blank(**fields: Any) -> dict[str, Any]:
    card: dict[str, Any] = {
        "answer_id": "",
        "kb_version": 0,
        "as_of": None,
        "superseded_since": None,
        "client": None,
        "route": "lookup",
        "status": "unsupported",
        "rule": {"text": "", "citations": []},
        "working": None,
        "decision": None,
        "exception_code": None,
        "next_owner": None,
        "older_sources": [],
        "expert_tip": None,
        "route_to": None,
        "entities": [],
        "related": [],
        "latency_ms": 0,
    }
    card.update(fields)
    return card


def view_for(card: dict[str, Any], viewer: str = "processor") -> dict[str, Any]:
    """A processor never sees text the verifier did not confirm; owners and evaluation do."""
    out = dict(card)
    if viewer in OWNER_VIEWERS:
        return out
    out.pop("draft", None)
    out.pop("diagnostics", None)
    if out.get("status") == "unverified":
        out["rule"] = {"text": "", "citations": []}
        out["working"] = None
        out["decision"] = None
        out["expert_tip"] = None
    return out
