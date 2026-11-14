"""Expert capture (BUILD_PLAN Phase 12, TEST_PLAN T10): an expert answers five questions about a
habit that newcomers would not know; the answers become one structured entry, checked against the
current rules, held for a named reviewer, and once approved published as a practice note.

    questions()        the five questions and who can review
    match_subject()    entities the "who or what" answer names (to link the note to them)
    check_rules()      compatible / conflict / no rule, against the rules in force now
    submit()           the entry as an `expert_capture` episode (one interview turn)
    publish_entry()    worker job `capture_entry`: one pending practice fact citing that turn,
                       plus a review item for the reviewer (approve, edit or reject)

An expert's words are input, not a rule (CLAUDE.md rule 13): the entry enters as an episode and
waits for review whatever the GOVERNANCE setting, and a practice note never overrides a rule
(rule 9). The answers are already structured, so no language model reads them into a fact; the
model is used only for the rule check. What a note is about and where it is filed come from the
plug-in (`capture:` in plugin.yaml); without one, the subject is a topic and the attribute
`other:practice_note`.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.graph.rows import CAPTURE_ORIGIN as ORIGIN
from app.ingest.connectors import EpisodeIn
from app.ingest.pipeline import CAPTURE_CHANNEL as CHANNEL
from app.plugins import registry
from app.store import entities as ents
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import search
from app.store.base import day_start
from app.worker import handler

CHECK_PROMPT_VERSION = "capture-check-v1"
PROCESS_OWNER = "Process owner"
MAX_RULES = 4

# Five generic questions: who or what, the habit, how to spot it, what to do, how it is known.
QUESTIONS: list[dict[str, str]] = [
    {
        "key": "subject",
        "label": "About",
        "ask": "Who or what is this about? A supplier, a client, a system, a kind of document…",
    },
    {"key": "habit", "label": "Habit", "ask": "What do they do that a newcomer would not expect?"},
    {
        "key": "trigger",
        "label": "How to spot it",
        "ask": "How do you spot it? What does it look like when it happens?",
    },
    {
        "key": "what_to_do",
        "label": "What to do",
        "ask": "What should someone do when they see it?",
    },
    {
        "key": "evidence",
        "label": "How you know",
        "ask": "How do you know, and since when? (an email, an incident, years of practice…)",
    },
]


class Entry(BaseModel):
    """One captured habit: the five answers, who gave them and when."""

    subject: str = Field(min_length=1, max_length=200)
    habit: str = Field(min_length=1, max_length=2000)
    trigger: str = Field(default="", max_length=2000)
    what_to_do: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(default="", max_length=2000)
    author: str = Field(min_length=1, max_length=120)
    author_role: str | None = Field(default=None, max_length=120)
    date: dt.date = Field(default_factory=dt.date.today)
    subject_entity_id: str | None = Field(
        default=None, description="the entity this note is about, chosen from match_subject()"
    )


class RuleRef(BaseModel):
    label: str
    locator: str
    text: str
    file: str | None = None


class RuleCheck(BaseModel):
    verdict: Literal["compatible", "conflict", "no_rule", "unchecked"]
    reason: str
    rules: list[RuleRef] = Field(default_factory=list)


class _CheckOut(BaseModel):
    verdict: Literal["compatible", "conflict", "no_rule"]
    rule: str | None = Field(None, description="the label of the rule it conflicts with, if any")
    reason: str = Field(description="one sentence")


# ---------------------------------------------------------------- configuration


@dataclass
class Filing:
    subject_type: str
    attribute: str


def filing() -> Filing:
    """Where captured notes go: the first plug-in's `capture:` settings, else generic."""
    for p in registry.plugins():
        cfg = p.manifest.get("capture") or {}
        if cfg.get("attribute"):
            return Filing(str(cfg.get("subject_type") or "topic"), str(cfg["attribute"]))
    return Filing("topic", "other:practice_note")


def reviewers() -> list[str]:
    """Who can review an entry: the plug-in's roles that own topics (not the askers)."""
    names = [r.get("name", k) for k, r in registry.roles().items() if not r.get("asker")]
    return list(dict.fromkeys([PROCESS_OWNER, *names]))


def questions() -> dict[str, Any]:
    return {"questions": QUESTIONS, "reviewers": reviewers(), "default_reviewer": PROCESS_OWNER}


# ---------------------------------------------------------------- the entry


def match_subject(session: Session, text: str, limit: int = 6) -> list[dict[str, str]]:
    """Entities the answer names (whole-word alias match), the plug-in's subject type first."""
    want = filing().subject_type
    found = {eid: (eid, typ, name) for eid, typ, name in search.entities_named_in(session, text)}
    exact = ents.by_alias(session, text.strip())
    if exact and exact not in found:
        e = ents.get(session, exact)
        if e is not None:
            found[exact] = (e.id, e.type, e.name)
    ranked = sorted(found.values(), key=lambda x: (x[1] != want, len(x[2])))
    return [{"id": i, "type": t, "name": n} for i, t, n in ranked[:limit]]


def _sentence(text: str) -> str:
    t = " ".join(text.split()).strip()
    return t if not t or t[-1] in ".!?" else t + "."


def statement(e: Entry, subject_name: str | None = None) -> str:
    """The note as it is shown beside answers: who, the habit, and what to do."""
    who = subject_name or e.subject.strip()
    return f"{who}: {_sentence(e.habit)} What to do: {_sentence(e.what_to_do)}"


def _speaker(name: str) -> str:
    """A name the transcript turn format accepts ("[00:00] Name: text")."""
    s = re.sub(r"[^\w.'\- ]+", " ", name.split("@")[0].replace(".", " ")).strip()
    s = re.sub(r"\s+", " ", s)[:40] or "Expert"
    return s[0].upper() + s[1:]


def transcript(e: Entry, subject_name: str | None = None) -> str:
    """The entry as a one-turn interview: one passage, the expert as speaker. The heading names
    it an interview, so the schema's practice ranking applies to it like any interview."""
    who = subject_name or e.subject.strip()
    said = [f"About {who}: {_sentence(e.habit)}"]
    if e.trigger.strip():
        said.append(f"How to spot it: {_sentence(e.trigger)}")
    said.append(f"What to do: {_sentence(e.what_to_do)}")
    if e.evidence.strip():
        said.append(f"How I know: {_sentence(e.evidence)}")
    role = f" ({e.author_role})" if e.author_role else ""
    return (
        f"# Expert interview — {who}: {e.habit.strip()[:70]}\n\n"
        f"| Title | Expert interview — {who} |\n| --- | --- |\n"
        f"| Date | {e.date.isoformat()} |\n"
        f"| Expert | {e.author}{role} |\n"
        f"| Recorded by | Expert capture |\n\n"
        f"[00:00] {_speaker(e.author)}: {' '.join(said)}\n"
    )


# ---------------------------------------------------------------- rule check

CHECK_SYSTEM = """You compare a colleague's practical habit with the rules currently in force.
A habit is know-how about how to apply rules in practice; it never changes a rule.
- conflict: following the habit would break, skip or contradict one of the rules (a different
  limit, approver, deadline or step than the rule requires).
- compatible: the habit fits the rules (it adds practical detail, a warning sign or an extra
  check, and following it still satisfies every rule).
- no_rule: none of the rules is about what the habit covers.
Judge only from the rules given. Answer with the label of the rule that conflicts, if any, and a
one-sentence reason."""


def check_rules(
    session: Session,
    e: Entry,
    structured_fn: Any = None,
    embed_fn: Any = None,
    rerank_fn: Any = None,
    today: dt.date | None = None,
) -> RuleCheck:
    """Compare the entry with the closest rules in force now (not practice notes)."""
    from app.answer.retrieve import retrieve
    from app.core.config import get_settings
    from app.graph.pipeline import active_ontology

    onto = active_ontology(session)
    practice = {r.doc_type for r in onto.source_ranking if r.practice} if onto else set()
    query = f"{e.subject} {e.habit} {e.trigger} {e.what_to_do}"
    got = retrieve(session, query, None, None, None, today or dt.date.today(), embed_fn, rerank_fn)
    rules = [p for p in got.passages if p.doc_type not in practice][:MAX_RULES]
    refs = [RuleRef(label=p.label, locator=p.locator, text=p.text[:600]) for p in rules]
    if not rules:
        return RuleCheck(verdict="no_rule", reason="No rule in force covers this.", rules=[])
    if structured_fn is None:
        if not get_settings().llm_configured:
            return RuleCheck(verdict="unchecked", reason="No model is configured.", rules=refs)
        from app.core.llm import structured as structured_fn
    rules_text = "\n\n".join(f"[{r.label}]\n{r.text}" for r in refs)
    out: _CheckOut = structured_fn(
        f"Habit about {e.subject}:\n{statement(e)}\nHow to spot it: {e.trigger}\n\n"
        f"Rules in force:\n\n{rules_text}",
        _CheckOut,
        system=CHECK_SYSTEM,
        model="fast",
        prompt_version=CHECK_PROMPT_VERSION,
        max_tokens=1024,
    )
    if out.verdict == "no_rule":
        return RuleCheck(verdict="no_rule", reason=out.reason, rules=[])
    named = [r for r in refs if out.rule and r.label == out.rule]
    return RuleCheck(verdict=out.verdict, reason=out.reason, rules=named or refs[:2])


# ---------------------------------------------------------------- submit and publish


def submit(
    session: Session,
    e: Entry,
    reviewer: str,
    check: RuleCheck | None = None,
    edited_from: str | None = None,
) -> str:
    """Register the entry as an episode (parsed by the worker, then `capture_entry`)."""
    from app.ingest.intake import submit as intake_submit

    subject_name = None
    if e.subject_entity_id:
        ent = ents.get(session, e.subject_entity_id)
        subject_name = ent.name if ent is not None else None
    meta = {
        "capture": {
            "entry": e.model_dump(mode="json"),
            "subject_name": subject_name or e.subject.strip(),
            "reviewer": reviewer,
            "check": check.model_dump(mode="json") if check else None,
            **({"edited_from": edited_from} if edited_from else {}),
        }
    }
    ep = EpisodeIn(
        channel=CHANNEL,
        data=transcript(e, subject_name).encode("utf-8"),
        filename=f"expert-capture-{e.date.isoformat()}.md",
        received_at=dt.datetime.now(dt.UTC),
        sender=e.author,
        sender_role=e.author_role,
        meta=meta,
    )
    episode_id, _ = intake_submit(session, ep)
    return episode_id


def _passage(session: Session, episode_id: str) -> Any | None:
    rows = estore.passages_for_episode(session, episode_id)
    turns = [p for p in rows if p.segment_kind in ("turn", "note")]
    return (turns or [p for p in rows if p.text.strip()] or [None])[0]


def publish_entry(session: Session, episode_id: str) -> dict[str, Any]:
    """One pending practice fact citing the entry's turn, and the review item for it."""
    from app.govern.apply import hold
    from app.govern.policy import PENDING, Verdict
    from app.graph.pipeline import active_ontology
    from app.graph.rows import _attribute

    ep = estore.get_episode(session, episode_id)
    cap = ((ep.meta or {}).get("capture") if ep is not None else None) or {}
    if ep is None or not cap:
        return {"skipped": "not an expert capture episode"}
    e = Entry.model_validate(cap["entry"])
    p = _passage(session, episode_id)
    if p is None:
        estore.set_status(session, episode_id, "needs_attention", error="no passage to cite")
        return {"skipped": "no passage"}
    where = filing()
    subject = cap.get("subject_name") or e.subject.strip()
    sid = (
        e.subject_entity_id
        if e.subject_entity_id and ents.get(session, e.subject_entity_id)
        else None
    )
    if sid is None:
        sid = ents.create(session, where.subject_type, subject, episode_id=episode_id)
    attr = _attribute(active_ontology(session), where.attribute)
    src = next((x for x in estore.list_sources(session, episode_id) if x.id == p.source_id), None)
    text = statement(e, subject)
    check = cap.get("check") or {}
    fid = fstore.insert(
        session,
        fstore.NewFact(
            origin_key=f"{ORIGIN}{p.id}:{attr}",
            subject_id=sid,
            attribute=attr,
            value={"type": "text", "text": text},
            statement=text,
            kind="practice",
            status="pending",
            quote=p.text[:500],
            passage_id=p.id,
            episode_id=episode_id,
            source_id=p.source_id,
            authority_rank=(src.authority_rank if src and src.authority_rank else 99),
            valid_from=day_start(e.date),
            meta={
                "origin": "expert capture",
                "author": e.author,
                "reviewer": cap.get("reviewer") or PROCESS_OWNER,
                "governance": "pending",
                "reason": "expert capture: held for review",
            },
        ),
    )
    reasons = [
        f"expert capture by {e.author}: a practice note, never a rule; "
        f"held for {cap.get('reviewer') or PROCESS_OWNER}"
    ]
    if check.get("verdict") == "conflict":
        reasons.append(f"rule check: possible conflict. {check.get('reason', '')}".strip())
    elif check.get("verdict"):
        reasons.append(f"rule check: {check['verdict'].replace('_', ' ')}")
    topic = attr.split(".", 1)[0] if not attr.startswith("other:") else "practice"
    item = hold(session, episode_id, Verdict(PENDING, reasons, [topic]), [fid])
    return {"fact_id": fid, "review_item": item, "subject_id": sid}


@handler("capture_entry")
def capture_entry_job(payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as s:
        return publish_entry(s, payload["episode_id"])


# ---------------------------------------------------------------- listing


def entries(session: Session, limit: int = 50) -> list[dict[str, Any]]:
    """Captured entries, newest first, with where each one is in review."""
    from app.store import kb

    eps = [x for x in estore.list_episodes(session, limit=1000) if x.channel == CHANNEL][:limit]
    items = {
        (i.payload or {}).get("episode_id"): i
        for status in ("open", "approved", "rejected", "edited")
        for i in kb.list_review_items(session, status=status)
        if i.kind == "change" and (i.payload or {}).get("channel") == CHANNEL
    }
    facts = {}
    for x in eps:
        live = fstore.live_for_episode(
            session, x.id, statuses=["current", "pending", "provisional"]
        )
        if live:
            facts[x.id] = live[0]
    out = []
    for x in eps:
        cap = (x.meta or {}).get("capture") or {}
        item = items.get(x.id)
        f = facts.get(x.id)
        out.append(
            {
                "episode_id": x.id,
                "status": x.status,
                "entry": cap.get("entry"),
                "subject_name": cap.get("subject_name"),
                "reviewer": cap.get("reviewer"),
                "check": cap.get("check"),
                "edited_from": cap.get("edited_from"),
                "received_at": x.received_at.isoformat() if x.received_at else None,
                "statement": f.statement if f else None,
                "fact_status": f.status if f else None,
                "approved_by": (f.meta or {}).get("approved_by") if f else None,
                "review": {
                    "id": item.id,
                    "status": item.status,
                    "row_version": item.row_version,
                    "decided_by": item.decided_by,
                }
                if item
                else None,
            }
        )
    return out


def known_notes(session: Session, limit: int = 40) -> dict[str, Any]:
    """Practice notes already in force (data rows, interviews, earlier captures): what the team
    knows, so an expert can see what is already written down before adding to it."""
    from app.graph.pipeline import active_ontology

    onto = active_ontology(session)
    practice = {r.doc_type for r in onto.source_ranking if r.practice} if onto else set()
    notes = fstore.get_facts(session, statuses=["current"], kinds=["practice"])
    hits = search.hydrate(session, sorted({f.passage_id for f in notes if f.passage_id}))
    rows = []
    for f in notes:
        h = hits.get(f.passage_id or "")
        own = f.origin_key.startswith(ORIGIN) or f.origin_key.startswith("row:")
        if not own and (h is None or h.doc_type not in practice):
            continue  # know-how only: interviews, observations, data-row notes, captures
        rows.append(
            {
                "statement": f.statement,
                "source": h.label if h else f.source_label,
                "author": (h.speaker if h else None) or (f.meta or {}).get("author"),
                "date": h.dated.isoformat() if h and h.dated else None,
                "origin": "capture"
                if f.origin_key.startswith(ORIGIN)
                else ("data row" if f.origin_key.startswith("row:") else "document"),
            }
        )
    rows.sort(key=lambda r: (r["origin"] != "capture", r["source"] or ""))
    by_origin: dict[str, int] = {}
    for r in rows:
        by_origin[r["origin"]] = by_origin.get(r["origin"], 0) + 1
    return {"total": len(rows), "by_origin": by_origin, "notes": rows[:limit]}
