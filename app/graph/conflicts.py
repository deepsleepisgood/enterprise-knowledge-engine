"""Conflict scan (BUILD_PLAN Phase 6): which sources disagree, and which one holds.

Resolution (`resolve.py`) records a conflict on write only when two *current* sources disagree.
The scan looks wider, over every live fact, so the owner also sees outdated statements that
still circulate (an old version, an FAQ that was never updated) next to the rule that holds:

1. Group live facts by (subject, attribute, client scope). The authoritative fact of a group is
   its `current` rule with the best authority rank (then the latest start).
2. Every other fact in the group is compared with it. Numbers in the same unit, identical
   wording and list subsets are settled without a model; anything else goes to a MODEL_SMART
   judge (same / narrower / different / unrelated), once per distinct (source, value).
3. Facts in groups with no current rule (an older document often files the same rule under
   another attribute name) are paired with their nearest current rules by embedding in the
   same client scope, and judged the same way.
4. A different value is a conflict: `value` across sources, `self_contradiction` inside one
   source, `practice_vs_rule` for expert practice. Each records both facts (so both passages),
   the authoritative fact and the reason (the precedence rule and the dates).

`exclude_passages` drops facts from given passages (for example a change table that states
the conflicts outright), so recall can be reported with and without it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.graph.compare import NUMERIC, compare_values
from app.store import facts as fstore
from app.store import kb
from app.store.base import tenant
from app.store.facts import FactRow
from app.store.models import Source

PROMPT_VERSION = "conflict-v2"
Judgement = Literal["same", "narrower", "different", "unrelated"]
NEIGHBOURS = 4
MIN_SIMILARITY = 0.75
JUDGE_THREADS = 4  # the LLM gateway still enforces the provider's rate and concurrency limits
OUTDATED = {"superseded", "overridden", "pending", "provisional", "stale"}


class ConflictVerdict(BaseModel):
    verdict: Judgement
    reason: str


SYSTEM = """You compare two statements from an organisation's documents.
Answer:
- 'unrelated' if they are not about the same parameter or step (different subjects, or one
  is about something the other does not cover);
- 'same' if they state the same rule in different words;
- 'narrower' if statement B is a special case or a subset of statement A and does not
  contradict it;
- 'different' if both are about the same parameter and following B would give a different
  result from following A (a different value, threshold, date, step, approver or list).
Judge only the rule, not the wording. The statements and parameter names were written by an
extraction model and can name the parameter imprecisely: when the source passages show that both
are about the same parameter, judge them as such."""


@dataclass
class Found:
    authoritative: FactRow
    other: FactRow
    kind: str  # value, self_contradiction, practice_vs_rule
    reason: str
    judged_by: str  # deterministic or model
    via: str = "group"  # group, scope (general vs client rule), self, passage or neighbour
    conflict_id: int | None = None
    # Other passages of the authoritative source that state the same value (a rule section
    # and its summary table): the owner sees all of them.
    support: list[FactRow] = field(default_factory=list)


@dataclass
class ScanReport:
    groups: int = 0
    compared: int = 0
    judged: int = 0
    undecided: int = 0
    found: list[Found] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    cleared: int = 0  # open conflicts from earlier scans this one no longer finds

    def summary(self) -> dict[str, Any]:
        kinds: dict[str, int] = defaultdict(int)
        for f in self.found:
            kinds[f.kind] += 1
        return {
            "groups": self.groups,
            "compared": self.compared,
            "judged": self.judged,
            "undecided": self.undecided,
            "conflicts": len(self.found),
            "by_kind": dict(kinds),
            "failures": len(self.failures),
            "cleared": self.cleared,
        }


Judge = Callable[[FactRow, FactRow], Judgement | None]


def value_text(f: FactRow) -> str:
    v = f.value or {}
    if v.get("items"):
        return ", ".join(str(x) for x in v["items"])
    if v.get("number") is not None:
        return f"{v['number']:g} {v.get('unit') or ''}".strip()
    return str(v.get("text") or "")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w%.]+", " ", s.lower())).strip()


def _items(f: FactRow) -> set[str]:
    v = f.value or {}
    raw = v.get("items") or re.split(r",|\band\b|;", str(v.get("text") or ""))
    return {_norm(str(x)) for x in raw if _norm(str(x))}


def quick_verdict(a: FactRow, b: FactRow) -> Judgement | None:
    """What can be settled without a model: numbers in one unit, identical wording, and a
    list that is part of the authoritative list. Anything else is for the judge."""
    va, vb = a.value or {}, b.value or {}
    verdict = compare_values(va, vb)
    if verdict == "same":
        return "same"
    numeric = va.get("type") in NUMERIC and vb.get("type") in NUMERIC
    if verdict == "different" and numeric:
        return "different"
    sa, sb = _items(a), _items(b)
    if len(sa) > 1 and sb and sb < sa:
        return "narrower"
    return None


class ModelJudge:
    """MODEL_SMART judgement (thinking off, cached) for what `quick_verdict` cannot settle."""

    def __init__(self, structured_fn: Callable[..., Any] | None = None) -> None:
        if structured_fn is None:
            from app.core.llm import structured

            structured_fn = structured
        self._structured = structured_fn
        self.failures: list[str] = []
        self.passage_text: dict[str, str] = {}  # filled by `scan` before judging

    def _side(self, tag: str, f: FactRow) -> str:
        source = self.passage_text.get(f.passage_id or "") or f.quote or ""
        return (
            f"Statement {tag} ({f.attribute}, about {f.subject_name or f.subject_id}):\n"
            f"{f.statement}\nValue {tag}: {value_text(f)}\n"
            f"Source passage {tag} ({f.source_label or ''} {f.locator or ''}):\n{source[:900]}"
        )

    def __call__(self, a: FactRow, b: FactRow) -> Judgement | None:
        prompt = f"{self._side('A', a)}\n\n{self._side('B', b)}"
        try:
            out: ConflictVerdict = self._structured(
                prompt,
                ConflictVerdict,
                system=SYSTEM,
                model="smart",
                prompt_version=PROMPT_VERSION,
                max_tokens=2048,
                thinking=False,
            )
        except Exception as exc:  # one failed judgement must not stop the scan
            self.failures.append(f"{a.id} vs {b.id}: {type(exc).__name__}: {exc}")
            return None
        return out.verdict


IN_FORCE = ("current", "corroborating")


@dataclass
class _Pair:
    auth: FactRow
    other: FactRow
    via: str
    group: list[FactRow]
    verdict: Judgement | None
    by: str = "deterministic"


def _unit(f: FactRow) -> str | None:
    """The unit of a numeric value ('' when unitless), None for text and lists."""
    v = f.value or {}
    if v.get("type") not in NUMERIC or v.get("number") is None:
        return None
    return _norm(str(v.get("unit") or "")).rstrip("s")


def _judge_all(session: Session, pairs: list[_Pair], judge: Judge | None, rep: ScanReport) -> None:
    """Judge every pair `quick_verdict` left open, in parallel (results are cached)."""
    todo = [p for p in pairs if p.verdict is None]
    if judge is None or not todo:
        return
    if isinstance(judge, ModelJudge):
        from app.store import episodes as estore

        pids = sorted({x.passage_id for p in todo for x in (p.auth, p.other) if x.passage_id})
        judge.passage_text.update(
            {pid: p.text or "" for pid, p in estore.passages_by_ids(session, pids).items()}
        )
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=JUDGE_THREADS) as pool:
        verdicts = list(pool.map(lambda p: judge(p.auth, p.other), todo))
    for p, v in zip(todo, verdicts, strict=True):
        rep.judged += 1
        p.verdict, p.by = v, "model"


def _client(f: FactRow) -> str:
    return str((f.scope or {}).get("client") or "all")


def _authoritative(group: list[FactRow]) -> FactRow | None:
    """The group's rule in force: `current` first, else one that `corroborates` a rule in force
    (its winner may sit in another group after re-keying)."""
    for statuses in (("current",), ("corroborating",)):
        rules = [f for f in group if f.status in statuses and f.kind != "practice"]
        if rules:
            return min(
                rules,
                key=lambda f: (
                    f.authority_rank,
                    -(f.valid_from.toordinal() if f.valid_from else 0),
                    f.id,
                ),
            )
    return None


def _label(sources: dict[str, Source], f: FactRow) -> str:
    s = sources.get(f.source_id or "")
    label = f.source_label or (s.short_label if s else "unknown source")
    return f"{label} {f.locator}" if f.locator and f.locator not in label else label


def reason(a: FactRow, b: FactRow, kind: str, sources: dict[str, Source]) -> str:
    """Why `a` holds over `b`: the precedence rule that applies, with the dates."""
    sa, sb = sources.get(a.source_id or ""), sources.get(b.source_id or "")
    da, db = (sa.dated if sa else None), (sb.dated if sb else None)
    when_a = f", dated {da:%d %b %Y}" if da else ""
    when_b = f", dated {db:%d %b %Y}" if db else ""
    la, lb = _label(sources, a), _label(sources, b)
    if kind == "self_contradiction":
        return (
            f"{la} states two different values ({value_text(a)}; {value_text(b)}); "
            f"the one resolved as in force is {value_text(a)}."
        )
    if kind == "practice_vs_rule":
        return f"Practice in {lb} differs from the rule in {la}{when_a}; practice never overrides."
    status_b = sb.status if sb else b.status
    if sa is not None and sb is not None and sa.supersedes_source_id == sb.id:
        why = f"{la}{when_a} replaced {lb}{when_b}"
    elif status_b == "superseded" or b.status == "superseded":
        why = f"{lb}{when_b} is superseded; {la}{when_a} is in force"
    elif status_b == "stale":
        why = f"{lb}{when_b} is stale; {la}{when_a} is current"
    elif a.authority_rank < b.authority_rank:
        why = (
            f"{la} (authority rank {a.authority_rank}{when_a}) outranks "
            f"{lb} (rank {b.authority_rank}{when_b})"
        )
    elif da and db and da > db:
        why = f"{la}{when_a} is later than {lb}{when_b}"
    else:
        why = f"{la}{when_a} holds; {lb}{when_b} disagrees"
    if _client(a) != "all":
        why += f" (for {_client(a)})"
    return why + "."


def _kind(auth: FactRow, other: FactRow) -> str:
    if other.kind == "practice":
        return "practice_vs_rule"
    if other.source_id and other.source_id == auth.source_id:
        return "self_contradiction"
    return "value"


# A passage that corrects itself ("... no approval needed. Correction: this requires approval")
# holds the contradiction in its own words, often across facts of different attributes.
SELF_CORRECTION = re.compile(
    r"\b(correction|corrected|erratum|errata|should read|is incorrect|is wrong|"
    r"this is not right|on second thought)\b",
    re.I,
)


class PassageVerdict(BaseModel):
    contradicts_itself: bool
    reason: str


PASSAGE_SYSTEM = """You read one passage from an organisation's document. Say whether it
contradicts itself: it states a rule or outcome and then states an incompatible one (for
example an example that is later corrected). A passage that only adds a condition or an
exception does not contradict itself."""


def passage_self_check(
    session: Session, rows: list[FactRow], structured_fn: Callable[..., Any] | None
) -> list[tuple[list[FactRow], str]]:
    """Passages with self-correction words, checked by MODEL_SMART: [(their facts, reason)]."""
    from app.store import episodes as estore

    by_passage: dict[str, list[FactRow]] = defaultdict(list)
    for f in rows:
        if f.passage_id:
            by_passage[f.passage_id].append(f)
    hits = estore.passages_by_ids(session, sorted(by_passage))
    out = []
    for pid, p in sorted(hits.items()):
        if not SELF_CORRECTION.search(p.text or "") or structured_fn is None:
            continue
        try:
            v: PassageVerdict = structured_fn(
                f"Passage ({p.locator}):\n{p.text[:3000]}",
                PassageVerdict,
                system=PASSAGE_SYSTEM,
                model="smart",
                prompt_version=PROMPT_VERSION,
                max_tokens=1024,
                thinking=False,
            )
        except Exception:
            continue
        if v.contradicts_itself:
            out.append((sorted(by_passage[pid], key=lambda f: f.id), v.reason))
    return out


def scan(
    session: Session,
    judge: Judge | None = None,
    exclude_passages: set[str] | None = None,
    record: bool = True,
    neighbours: int = NEIGHBOURS,
    min_similarity: float = MIN_SIMILARITY,
) -> ScanReport:
    """Scan the live graph for conflicts. With `judge=None` only what `quick_verdict` settles
    is reported (the rest is counted as undecided)."""
    exclude = exclude_passages or set()
    rows = [
        f
        for f in fstore.get_facts(session)
        if not f.attribute.startswith("other:") and f.passage_id not in exclude
    ]
    by_id = {f.id: f for f in rows}
    sources = {s.id: s for s in session.scalars(select(Source).where(Source.tenant_id == tenant()))}
    groups: dict[tuple[str, str, str], list[FactRow]] = defaultdict(list)
    for f in rows:
        groups[(f.subject_id, f.attribute, _client(f))].append(f)

    rep = ScanReport()
    seen: set[tuple[int, str, str]] = set()  # (authoritative id, other source, other value)
    pairs: list[_Pair] = []

    def outdated(f: FactRow) -> bool:
        s = sources.get(f.source_id or "")
        return f.status in OUTDATED or (s is not None and s.status in OUTDATED)

    def compare(auth: FactRow, other: FactRow, via: str, group: list[FactRow] = ()) -> None:
        key = (auth.id, other.source_id or "", _norm(value_text(other)))
        if key in seen or other.id == auth.id:
            return
        seen.add(key)
        rep.compared += 1
        verdict = quick_verdict(auth, other)
        # A neighbour is another attribute: equal or different values say nothing until the
        # judge has read both statements. Inside one group, different numbers settle a conflict
        # only across two sources (one source may state two conditions). A shorter list in an
        # outdated document is usually the old rule (one approver where there are now two),
        # not a partial mention, so the judge reads it.
        if (
            via == "neighbour"
            or (verdict == "different" and _kind(auth, other) != "value")
            or (verdict == "narrower" and outdated(other))
        ):
            verdict = None
        pairs.append(_Pair(auth, other, via, list(group), verdict))

    orphans: list[FactRow] = []
    for _key, group in sorted(groups.items()):
        auth = _authoritative(group)
        if auth is None:
            orphans += group
            continue
        if len(group) < 2:
            continue
        rep.groups += 1
        for other in group:
            compare(auth, other, "group", group)

    # A general statement with no rule of its own in force, against the same parameter's rule
    # for each client ("only APIs need release" for everyone vs a Pharma memo's list).
    client_rules: dict[str, list[FactRow]] = defaultdict(list)
    for (_s, attr, client), group in groups.items():
        auth = _authoritative(group)
        if client != "all" and auth is not None:
            client_rules[attr].append(auth)
    for f in orphans:
        if _client(f) == "all":
            for rule_ in client_rules.get(f.attribute, []):
                compare(rule_, f, "scope")

    # Inside one document, whatever its status: two values for one parameter (a worked example
    # that contradicts its own rule). Judged for each source separately.
    own: dict[tuple[str, str, str, str], list[FactRow]] = defaultdict(list)
    for f in rows:
        if f.source_id and f.kind != "practice":
            own[(f.source_id, f.subject_id, f.attribute, _client(f))].append(f)
    for group in own.values():
        values = {_norm(value_text(f)): f for f in sorted(group, key=lambda f: f.id)}
        if len(values) < 2:
            continue
        first, *rest = values.values()
        for other in rest:
            compare(first, other, "self")

    # Passages that correct themselves.
    structured_fn = judge._structured if isinstance(judge, ModelJudge) else None
    self_found: list[Found] = []
    for facts_, why in passage_self_check(session, rows, structured_fn):
        rep.judged += 1
        a, b = facts_[0], facts_[-1]
        self_found.append(
            Found(
                a,
                b,
                "self_contradiction",
                f"{_label(sources, a)} contradicts itself: {why}",
                "model",
                "passage",
            )
        )

    # One fact per (source, value) is enough to find the rule it disagrees with.
    firsts: dict[tuple[str, str, str], FactRow] = {}
    for f in orphans:
        firsts.setdefault((f.source_id or "", f.attribute, _norm(value_text(f))), f)
    hits = fstore.nearest_current(
        session, [f.id for f in firsts.values()], k=neighbours, min_sim=min_similarity
    )
    near = fstore.by_ids(session, sorted({c for _, c, _ in hits} - set(by_id)))
    hit_passages: dict[int, set[str]] = defaultdict(set)
    for fid, cid, _sim in hits:
        cur = by_id.get(cid) or near.get(cid)
        if cur is not None and cur.passage_id not in exclude and fid in by_id:
            compare(cur, by_id[fid], "neighbour")
            if cur.passage_id:
                hit_passages[fid].add(cur.passage_id)
    # The neighbour found the passage that states the rule, but the matching number may sit in
    # a sibling fact of that passage ("cement, steel, sand: up to 5%" -> materials and 5%).
    siblings = fstore.live_for_passages(
        session, sorted({p for ps in hit_passages.values() for p in ps})
    )
    by_passage: dict[str, list[FactRow]] = defaultdict(list)
    for c in siblings:
        if c.status in IN_FORCE and c.kind != "practice" and not c.attribute.startswith("other:"):
            by_passage[c.passage_id or ""].append(c)
    for fid, pids in sorted(hit_passages.items()):
        f = by_id[fid]
        unit = _unit(f)
        if unit is None:
            continue
        for pid in sorted(pids):
            for c in by_passage.get(pid, []):
                if _unit(c) == unit:
                    compare(c, f, "neighbour")

    _judge_all(session, pairs, judge, rep)
    for p in pairs:
        if p.verdict is None:
            rep.undecided += 1
        elif p.verdict == "different":
            kind = _kind(p.auth, p.other)
            support = [
                f
                for f in p.group
                if f.id != p.auth.id
                and f.source_id == p.auth.source_id
                and f.passage_id != p.auth.passage_id
                and quick_verdict(p.auth, f) == "same"
            ]
            rep.found.append(
                Found(
                    p.auth,
                    p.other,
                    kind,
                    reason(p.auth, p.other, kind, sources),
                    p.by,
                    p.via,
                    None,
                    support,
                )
            )
    rep.found += self_found

    if isinstance(judge, ModelJudge):
        rep.failures += judge.failures
    if record:
        for c in rep.found:
            c.conflict_id = kb.upsert_conflict(
                session,
                subject_id=c.authoritative.subject_id,
                attribute=c.authoritative.attribute,
                scope={"client": _client(c.authoritative)},
                fact_a=c.authoritative.id,
                fact_b=c.other.id,
                kind=c.kind,
                authoritative_fact=c.authoritative.id,
                reason=c.reason,
            )
        if not exclude and not rep.failures:  # only a complete scan can say what is gone
            rep.cleared = kb.clear_conflicts_except(
                session, {c.conflict_id for c in rep.found if c.conflict_id}
            )
    return rep


def scan_tenant(exclude_passages: set[str] | None = None, judge: Judge | None = None) -> dict:
    """Run a full scan and record it (used by the API and the job worker)."""
    from app.core.db import session_scope

    with session_scope() as s:
        rep = scan(s, judge=judge or ModelJudge(), exclude_passages=exclude_passages)
        return rep.summary()


def conflict_scan_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Worker job `conflict_scan` (queued by POST /conflict-scan)."""
    return scan_tenant(exclude_passages=set(payload.get("exclude_passages") or []))


def _register() -> None:
    from app.worker import handler

    handler("conflict_scan")(conflict_scan_job)


_register()


def describe(f: Found) -> dict[str, Any]:
    """A conflict as callers see it: both sides with source, locator and value, and the reason."""

    def side(x: FactRow) -> dict[str, Any]:
        return {
            "fact_id": x.id,
            "passage_id": x.passage_id,
            "source": x.source_label,
            "locator": x.locator,
            "value": value_text(x),
            "statement": x.statement,
            "status": x.status,
        }

    return {
        "kind": f.kind,
        "topic": f"{f.authoritative.subject_name or ''} {f.authoritative.attribute}".strip(),
        "authoritative": side(f.authoritative),
        "also_stated_in": [side(x) for x in f.support],
        "conflicting": side(f.other),
        "reason": f.reason,
        "judged_by": f.judged_by,
        "via": f.via,
        "conflict_id": f.conflict_id,
    }
