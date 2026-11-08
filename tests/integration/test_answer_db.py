"""Phase 4 answer pipeline against the database, with fake LLM, embeddings and reranker.

Uses the leave-policy corpus from test_graph_db (two policy versions, a client memo, an
interview): current answers, as-of answers, client scope, abstention, out-of-scope, the
verifier withholding a superseded value, and escalation to an expert.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import date

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
    return [len(qw & set(WORD.findall(d.lower()))) - 5.0 for d in docs]


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
            return RouteOut(route="lookup", client=client, confidence=0.9)
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
    assert llm.calls == ["RouteOut"]


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


def test_report_wrong_answer_creates_an_owner_item(kb_built) -> None:
    from app.store import kb

    card = run("How many days of annual leave do staff get?")
    escalate.report_wrong(int(card["answer_id"]), "processor-2", "looks off")
    with session_scope() as s:
        assert [i.kind for i in kb.list_review_items(s)].count("report") == 1
