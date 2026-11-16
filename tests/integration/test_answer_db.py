"""Phase 4 answer pipeline against the database, with fake LLM, embeddings and reranker.

Uses the leave-policy corpus from test_graph_db (two policy versions, a client memo, an
interview): current answers, as-of answers, client scope, abstention, out-of-scope, the
verifier withholding a superseded value, and escalation to an expert.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, date, datetime

import pytest

from app.answer import escalate
from app.answer.generate import GenOut, Quote, Sentence
from app.answer.index import index_all
from app.answer.pipeline import ask
from app.answer.router import RouteOut
from app.answer.verify import SupportItem, SupportOut
from app.core.db import session_scope
from app.store import answers as astore
from app.store import episodes as estore
from tests.integration.test_graph_db import INTERVIEW, MEMO, V1, V2, graph  # noqa: F401

pytestmark = pytest.mark.db
TODAY = date(2026, 6, 1)
WORD = re.compile(r"[a-z0-9]+")


def fake_embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        v = [0.0] * 384
        for w in WORD.findall(t.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 384] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


STOP = {
    "the",
    "a",
    "of",
    "do",
    "how",
    "many",
    "is",
    "what",
    "get",
    "staff",
    "are",
    "on",
    "there",
    "for",
}


def fake_rerank(q: str, docs: list[str]) -> list[float]:
    qw = set(WORD.findall(q.lower())) - STOP
    # No shared word scores 1 below the abstain gate (ABSTAIN_RERANK_SCORE -6), one word meets it.
    return [len(qw & set(WORD.findall(d.lower()))) - 7.0 for d in docs]


def passages_in(prompt: str) -> dict[str, str]:
    """P-id -> passage text, parsed from the generation prompt."""
    body = prompt.split("Passages:\n\n", 1)[1].split("\n\nYour previous draft", 1)[0]
    out = {}
    for block in re.split(r"\n\n(?=\[P\d+\] )", body):
        m = re.match(r"\[(P\d+)\] [^\n]*\n(.*)", block, re.S)
        if m:
            out[m.group(1)] = m.group(2)
    return out


class FakeLLM:
    def __init__(self, lie: bool = False) -> None:
        self.lie = lie
        self.calls: list[str] = []

    def __call__(self, prompt, schema, **kw):
        self.calls.append(schema.__name__)
        if schema is RouteOut:
            if "weather" in prompt:
                return RouteOut(
                    route="out_of_scope", confidence=0.9, out_of_scope_reason="general_knowledge"
                )
            client = "Northwind Builders" if "Northwind" in prompt else None
            as_of = "2025-06-15" if "In June 2025" in prompt else None
            return RouteOut(route="lookup", client=client, confidence=0.9, as_of=as_of)
        if schema is GenOut:
            ps = passages_in(prompt)
            if self.lie:  # states the superseded value while citing the current passage
                pid = next(p for p, t in ps.items() if "24 days" in t)
                return GenOut(
                    status="answered",
                    sentences=[Sentence(text="Staff get 20 days of annual leave.", sources=[pid])],
                    quotes=[Quote(source=pid, quote="24 days of annual leave")],
                )
            want = "20 days" if "As of: 2025" in prompt else "24 days"
            if "Client: Northwind" in prompt:
                want = "30 days"
            for pid, text in ps.items():
                m = re.search(rf"[^.\n]*{want}[^.\n]*", text)
                if m:
                    sent = m.group(0).strip()
                    return GenOut(
                        status="answered",
                        sentences=[Sentence(text=sent + ".", sources=[pid])],
                        quotes=[Quote(source=pid, quote=sent)],
                        related=["Can leave be cashed out?"],
                    )
            return GenOut(status="unsupported", reason="not in the passages")
        if schema is SupportOut:
            n = len(re.findall(r"^Sentence \d+:", prompt, re.M))
            return SupportOut(
                items=[SupportItem(sentence=i, supported=True) for i in range(1, n + 1)]
            )
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def kb_built(graph):  # noqa: F811
    ingest, build = graph
    for text, name in [
        (V1, "leave_v1.md"),
        (V2, "leave_v2.md"),
        (MEMO, "memos.md"),
        (INTERVIEW, "interviews.md"),
    ]:
        ingest(text, name)
    assert not build()["failures"]
    counts = index_all(fake_embed)
    assert counts["passages"] > 0 and counts["facts"] > 0
    return counts


def run(question: str, llm: FakeLLM | None = None, **kw) -> dict:
    return ask(
        question,
        today=TODAY,
        structured_fn=llm or FakeLLM(),
        embed_fn=fake_embed,
        rerank_fn=fake_rerank,
        **kw,
    )


def test_current_answer_cites_the_current_version_and_lists_the_older_one(kb_built) -> None:
    card = run("How many days of annual leave do staff get?")
    assert card["status"] == "answered", card.get("diagnostics")
    assert "24 days" in card["rule"]["text"] and "[1]" in card["rule"]["text"]
    (c,) = card["rule"]["citations"]
    assert c["file"] == "leave_v2.md" and "24 days" in c["quote"]
    older = card["older_sources"]
    assert older and older[0]["older_value"].startswith("20") and older[0]["current_value"]
    assert older[0]["superseded_on"] == "2026-01-01"
    assert "diagnostics" not in card and card["answer_id"]
    with session_scope() as s:
        logged = astore.get_answer(s, int(card["answer_id"]))
        assert logged.cited_fact_ids and logged.card["diagnostics"]["verifier"]["verified"]


def test_as_of_answer_uses_the_rule_in_force_then(kb_built) -> None:
    card = run("How many days of annual leave do staff get?", as_of=date(2025, 6, 1))
    assert card["status"] == "answered", card.get("diagnostics")
    assert "20 days" in card["rule"]["text"] and card["as_of"] == "2025-06-01"
    assert card["rule"]["citations"][0]["file"] == "leave_v1.md"
    assert card["superseded_since"] == "2026-01-01"


def test_a_date_asked_about_in_words_works_like_the_picker(kb_built) -> None:
    card = run("In June 2025, how many days of annual leave did staff get?")
    assert card["status"] == "answered", card.get("diagnostics")
    assert "20 days" in card["rule"]["text"] and card["as_of"] == "2025-06-15"


def test_client_memo_applies_to_its_client(kb_built) -> None:
    card = run("How many days of annual leave do Northwind staff get?")
    assert card["client"] == "Northwind Builders Ltd"
    assert "30 days" in card["rule"]["text"], card


def test_weak_retrieval_abstains_and_routes(kb_built) -> None:
    llm = FakeLLM()
    card = run("Is there a canteen subsidy for night shifts?", llm)
    assert card["status"] == "unsupported" and card["rule"]["text"] == ""
    assert card["route_to"]["role"]
    assert "GenOut" not in llm.calls


def test_out_of_scope_never_reaches_generation(kb_built) -> None:
    llm = FakeLLM()
    card = run("What will the weather be tomorrow?", llm)
    assert card["status"] == "unsupported" and card["route"] == "out_of_scope"
    # Only the router (plus the calculator inputs read early, in parallel) — never generation.
    assert "RouteOut" in llm.calls and set(llm.calls) <= {"RouteOut", "ScenarioParams"}


def test_superseded_value_is_withheld_after_one_retry(kb_built) -> None:
    llm = FakeLLM(lie=True)
    shown = run("How many days of annual leave do staff get?", llm)
    assert llm.calls.count("GenOut") == 2
    assert shown["status"] == "unverified" and shown["rule"]["text"] == ""
    assert "draft" not in shown and shown["route_to"]
    with session_scope() as s:
        full = astore.get_answer(s, int(shown["answer_id"])).card
    assert "20 days" in full["draft"]["rule"]["text"]
    assert any("not the current rule" in p for p in full["draft"]["problems"])


def test_escalation_reply_is_labelled_and_enters_as_an_episode(kb_built) -> None:
    card = run("Is there a canteen subsidy for night shifts?")
    sent = escalate.escalate(int(card["answer_id"]), asked_by="processor-1")
    assert sent["message"].startswith("Sent to ")
    with session_scope() as s:
        (e,) = astore.list_escalations(s)
        assert e.question.startswith("Is there a canteen") and e.found["status"] == "unsupported"
    out = escalate.reply(sent["escalation_id"], "hr-lead", "Night shifts get a 50% subsidy.")
    with session_scope() as s:
        ep = estore.get_episode(s, out["episode_id"])
        assert ep.channel == "expert_answer" and ep.sender == "hr-lead"
        (note,) = astore.notifications_for(s, "processor-1")
        assert note["body"].startswith(escalate.EXPERT_LABEL)
        assert astore.get_escalation(s, sent["escalation_id"]).status == "answered"
    # Nothing from the reply is published yet, so nothing is re-asked.
    assert escalate.reask_if_published(out["episode_id"]) == []


def test_publishing_the_reply_closes_its_unconfirmed_notice(kb_built, monkeypatch) -> None:
    import types

    from app.answer import pipeline
    from app.store import facts as fstore

    card = run("Is there a canteen subsidy for night shifts?")
    sent = escalate.escalate(int(card["answer_id"]), asked_by="processor-2")
    out = escalate.reply(sent["escalation_id"], "hr-lead", "Night shifts get a 50% subsidy.")
    # The owner approved: a fact from the reply is in force, and the question is asked again.
    monkeypatch.setattr(
        fstore, "live_for_episode", lambda s, ep, statuses: [types.SimpleNamespace(id=1)]
    )
    monkeypatch.setattr(pipeline, "ask", lambda q, **kw: {**card, "answer_id": card["answer_id"]})
    assert len(escalate.reask_if_published(out["episode_id"])) == 1
    with session_scope() as s:
        notes = {n["kind"]: n for n in astore.notifications_for(s, "processor-2")}
    assert notes["expert_reply"]["read"] and not notes["reanswered"]["read"]


class PublishWhileAnswering(FakeLLM):
    """While the router runs, the owner approves a change that retires the 24-day rule and the
    worker's recall runs at once: all before the answer is saved."""

    published = False

    def __call__(self, prompt, schema, **kw):
        if schema is RouteOut and not self.published:
            self.published = True
            from sqlalchemy import select

            from app.store import facts as fstore
            from app.store import kb
            from app.store.models import Fact
            from app.worker import run_one

            with session_scope() as s:
                ids = s.scalars(
                    select(Fact.id).where(
                        Fact.statement.ilike("%24 days%"),
                        Fact.status == "current",
                        Fact.retracted_at.is_(None),
                    )
                ).all()
                assert ids
                v = kb.bump_kb_version(s, "leave policy v3 approved")
                for fid in ids:
                    closed = fstore.revise(s, fid, valid_to=datetime(2026, 5, 31, tzinfo=UTC))
                    kb.record_change(s, v, "Annual leave: 24 -> 26 days", old_fact=closed)
            assert run_one("test-worker", ["answer_recall"])  # finds nothing: not saved yet
        return super().__call__(prompt, schema, **kw)


def test_a_change_published_while_answering_still_reaches_the_asker(kb_built) -> None:
    import app.distribute.recall  # noqa: F401 - registers the answer_recall handler
    from app.store import kb
    from app.worker import run_one

    with session_scope() as s:
        before = kb.current_kb_version(s)
    card = run(
        "How many days of annual leave do staff get?", PublishWhileAnswering(), user_id="pat"
    )
    # One snapshot: the whole card is the rule as it stood when the question was asked.
    assert card["status"] == "answered" and "24 days" in card["rule"]["text"], card
    assert card["kb_version"] == before
    with session_scope() as s:
        assert not astore.notifications_for(s, "pat")
    assert run_one("test-worker", ["answer_recall"])  # queued again when the answer was saved
    with session_scope() as s:
        (note,) = astore.notifications_for(s, "pat")
        assert note["answer_id"] == int(card["answer_id"]) and "24 -> 26" in note["body"]


def test_an_answer_on_the_latest_version_queues_no_recall(kb_built) -> None:
    from app.answer.pipeline import recall_if_published_meanwhile
    from app.store import kb

    with session_scope() as s:
        now = kb.kb_version_count(s)
    assert not recall_if_published_meanwhile({"kb_count": now, "cited_facts": True})
    assert not recall_if_published_meanwhile({"kb_count": now - 1, "cited_facts": False})
    assert recall_if_published_meanwhile({"kb_count": now - 1, "cited_facts": True})


def test_report_wrong_answer_creates_an_owner_item(kb_built) -> None:
    from app.store import kb

    card = run("How many days of annual leave do staff get?")
    escalate.report_wrong(int(card["answer_id"]), "processor-2", "looks off")
    with session_scope() as s:
        assert [i.kind for i in kb.list_review_items(s)].count("report") == 1


def test_reranker_scores_only_rerank_k_candidates_cut_to_rerank_chars(
    kb_built, monkeypatch
) -> None:
    from app.answer.retrieve import retrieve
    from app.core.config import get_settings

    seen: list[list[str]] = []

    def recording(q: str, docs: list[str]) -> list[float]:
        seen.append(docs)
        return fake_rerank(q, docs)

    monkeypatch.setenv("RERANK_K", "2")
    monkeypatch.setenv("RERANK_CHARS", "40")
    get_settings.cache_clear()
    try:
        with session_scope() as s:
            got = retrieve(
                s,
                "How many days of annual leave?",
                today=TODAY,
                embed_fn=fake_embed,
                rerank_fn=recording,
            )
    finally:
        get_settings.cache_clear()
    (docs,) = seen
    assert 1 <= len(docs) <= 2 and all(len(d) <= 40 for d in docs)
    assert got.scorer == "rerank" and len(got.passages) <= 2
