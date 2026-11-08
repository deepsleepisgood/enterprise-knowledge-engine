"""Phase 7 API: every endpoint against the test database (fake LLM, embeddings and reranker).

Uses the leave-policy graph from test_answer_db (two policy versions, a client memo, an
interview), so answers, timelines and as-of reads have real versions to show.
"""

from __future__ import annotations

import base64
import functools

import pytest
from fastapi.testclient import TestClient

from app.answer.pipeline import ask as real_ask
from app.api import ask as ask_route
from app.api.main import create_app
from app.core.db import session_scope
from app.store import facts as fstore
from app.store import kb
from tests.integration.test_answer_db import (  # noqa: F401
    TODAY,
    FakeLLM,
    fake_embed,
    fake_rerank,
    kb_built,
)
from tests.integration.test_graph_db import graph  # noqa: F401

pytestmark = pytest.mark.db
QUESTION = "How many days of annual leave do staff get?"


@pytest.fixture
def api(kb_built, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        ask_route,
        "answer",
        functools.partial(
            real_ask,
            today=TODAY,
            structured_fn=FakeLLM(),
            embed_fn=fake_embed,
            rerank_fn=fake_rerank,
        ),
    )
    with TestClient(create_app()) as client:
        yield client


def leave_entity(api: TestClient) -> str:
    with session_scope() as s:
        f = next(f for f in fstore.get_facts(s) if "24 days" in f.statement)
    return f.subject_id


def test_health_version_scopes_and_schema(api: TestClient) -> None:
    h = api.get("/health")
    assert h.status_code == 200 and h.json() == {"status": "ok", "db": True}
    v = api.get("/version")
    assert v.status_code == 200 and v.json()["kb_version"] >= 1 and v.json()["schema_version"]
    assert v.headers["x-kb-version"] == str(v.json()["kb_version"])
    scopes = api.get("/scopes").json()
    assert scopes[0] == {"key": "all", "label": "All clients"}
    assert any("Northwind" in s["label"] for s in scopes)
    sc = api.get("/schema").json()
    assert sc["active"]["status"] == "frozen" and sc["draft"] is None and sc["kb_version"] >= 1


def test_ask_returns_a_cited_card_with_kb_version(api: TestClient) -> None:
    r = api.post("/ask", json={"question": QUESTION, "user_id": "u1"})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["status"] == "answered" and "24 days" in card["rule"]["text"]
    assert card["rule"]["citations"][0]["file"] == "leave_v2.md"
    assert "x-kb-version" in r.headers and "diagnostics" not in card
    old = api.post("/ask", json={"question": QUESTION, "as_of": "2025-06-01"}).json()
    assert "20 days" in old["rule"]["text"] and old["as_of"] == "2025-06-01"
    assert api.post("/ask", json={"question": QUESTION, "invoice_id": "NOPE"}).status_code == 404
    assert api.post("/ask", json={"question": ""}).status_code == 422


def test_episodes_text_eml_upload_status_and_original(api: TestClient) -> None:
    r = api.post("/episodes", json={"text": "Night shifts end at 6 am.", "sender": "ops"})
    assert r.status_code == 202, r.text
    (ep,) = r.json()["episodes"]
    assert ep["created"]
    again = api.post("/episodes", json={"text": "Night shifts end at 6 am.", "sender": "ops"})
    assert again.json()["episodes"][0] == {**ep, "created": False}  # same content: deduped
    eml = (
        b"From: hr@example.com\r\nSubject: Leave carry-over\r\nDate: Mon, 2 Mar 2026 10:00:00"
        b" +0000\r\n\r\nUp to 5 days of leave carry over.\r\n"
    )
    r = api.post("/episodes", json={"eml_base64": base64.b64encode(eml).decode()})
    assert r.status_code == 202 and r.json()["episodes"]
    assert api.post("/episodes", json={"eml_base64": "***"}).status_code == 422
    assert api.post("/episodes", json={}).status_code == 422
    up = api.post(
        "/episodes/upload",
        files=[("files", ("note.md", b"# Note\n\nParking is free on Sundays.", "text/markdown"))],
    )
    assert up.status_code == 202, up.text
    listed = {e["id"] for e in api.get("/episodes").json()}
    assert ep["episode_id"] in listed and "blob_path" not in api.get("/episodes").json()[0]
    one = api.get(f"/episodes/{ep['episode_id']}").json()
    assert one["status"] == "queued" and one["has_original"] and one["facts"]["total"] == 0
    raw = api.get(f"/episodes/{ep['episode_id']}/original")
    assert raw.status_code == 200 and b"Night shifts" in raw.content
    assert api.get("/episodes/nope").status_code == 404
    assert api.get("/episodes/nope/original").status_code == 404


def test_entities_timeline_facts_and_passages(api: TestClient) -> None:
    ents = api.get("/entities").json()
    assert ents and {"id", "type", "name", "aliases"} <= set(ents[0])
    eid = leave_entity(api)
    one = api.get(f"/entities/{eid}").json()
    assert any("24" in str(f["value"]) for f in one["facts"])
    tl = api.get(f"/entities/{eid}/timeline").json()
    versions = [v for a in tl["attributes"] for v in a["versions"]]
    statuses = {v["status"] for v in versions}
    assert "current" in statuses and "superseded" in statuses  # history kept, nothing deleted
    then = api.get("/facts", params={"entity": eid, "valid_on": "2025-06-01"}).json()
    assert then and all("24 days" not in f["statement"] for f in then)
    assert api.get("/facts", params={"valid_on": "June"}).status_code == 422
    pid = next(f["passage_id"] for f in one["facts"] if f["passage_id"])
    p = api.get(f"/passages/{pid}").json()
    assert p["source"]["short_label"] and p["position_in_source"]["of"] >= 1 and p["facts"]
    assert "embedding" not in p and "tsv" not in p
    assert api.get("/passages/nope").status_code == 404
    assert api.get(f"/entities/{eid}/timeline?attribute=none.none").json()["attributes"] == []
    assert api.post(f"/entities/{eid}/split").status_code == 501


def test_entity_merge(api: TestClient) -> None:
    clients = api.get("/entities").json()
    a, b = clients[0]["id"], clients[1]["id"]
    assert (
        api.post("/entities/merge", json={"keep_id": a, "drop_id": a, "by": "o"}).status_code == 422
    )
    r = api.post("/entities/merge", json={"keep_id": a, "drop_id": b, "by": "owner"})
    assert r.status_code == 200 and r.json()["merged"] == b
    assert b not in {e["id"] for e in api.get("/entities").json()}
    bad = api.post("/entities/merge", json={"keep_id": a, "drop_id": "nope", "by": "o"})
    assert bad.status_code == 404


def test_plugins_bindings_calculate_context_invoices(api: TestClient) -> None:
    ps = api.get("/plugins").json()
    assert ps and ps[0]["calculators"] and "input_schema" in ps[0]["calculators"][0]
    assert isinstance(api.get("/bindings").json(), list)
    assert (
        api.put("/bindings/999999", json={"attribute_key": "x", "confirmed_by": "o"}).status_code
        == 404
    )
    assert api.post("/calculate/nope/price", json={"params": {}}).status_code == 404
    name = ps[0]["name"]
    fam = ps[0]["calculators"][0]["family"]
    assert api.post(f"/calculate/{name}/nope", json={"params": {}}).status_code == 404
    bad = api.post(f"/calculate/{name}/{fam}", json={"params": {}})
    assert bad.status_code == 422  # missing inputs (or no rule in this corpus): never a default
    assert api.get("/invoices", params={"q": "INV"}).json() == []  # no operations data loaded
    assert api.get("/context").status_code == 422
    assert api.get("/context", params={"invoice_id": "INV1"}).status_code == 404


def test_changes_and_acknowledgements(api: TestClient) -> None:
    feed = api.get("/changes", params={"since": 0}).json()
    assert feed, "publishing the graph records changes"
    c = feed[0]
    assert {"id", "kb_version", "summary", "old_value", "new_value", "status"} <= set(c)
    r = api.post(f"/changes/{c['id']}/ack", json={"user_id": "u1"})
    assert r.status_code == 200
    api.post(f"/changes/{c['id']}/ack", json={"user_id": "u1"})  # idempotent
    again = next(x for x in api.get("/changes").json() if x["id"] == c["id"])
    assert again["acknowledged"] == 1
    assert api.post("/changes/999999/ack", json={"user_id": "u1"}).status_code == 404
    latest = max(x["kb_version"] for x in feed)
    assert api.get("/changes", params={"since": latest}).json() == []


def test_review_queue_uses_row_version(api: TestClient) -> None:
    with session_scope() as s:
        item = kb.add_review_item(s, "change", {"summary": "leave from 24 to 25 days"})
    queue = api.get("/review-queue").json()
    it = next(i for i in queue if i["id"] == item)
    body = {"decision": "approve", "by": "owner", "row_version": it["row_version"]}
    stale = {**body, "row_version": it["row_version"] + 5}
    assert api.post(f"/review/{item}", json=stale).status_code == 409
    ok = api.post(f"/review/{item}", json=body)
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert api.post(f"/review/{item}", json=body).status_code == 409  # already decided
    assert item not in {i["id"] for i in api.get("/review-queue").json()}
    assert api.post("/review/999999", json=body).status_code == 404
    with session_scope() as s:
        item2 = kb.add_review_item(s, "change", {"summary": "x"})
    edit = {"decision": "edit", "by": "owner", "row_version": 1}
    assert api.post(f"/review/{item2}", json=edit).status_code == 422


def test_escalation_reply_close_and_report(api: TestClient) -> None:
    card = api.post("/ask", json={"question": "Is there a canteen subsidy?", "user_id": "u2"})
    aid = int(card.json()["answer_id"])
    r = api.post("/escalations", json={"answer_id": aid, "asked_by": "u2"})
    assert r.status_code == 201, r.text
    eid = r.json()["escalation_id"]
    assert eid in {e["id"] for e in api.get("/escalations").json()}
    rep = api.post(f"/escalations/{eid}/reply", json={"expert_id": "x1", "text": "No subsidy."})
    assert rep.status_code == 202 and rep.json()["episode_id"]
    assert eid not in {e["id"] for e in api.get("/escalations").json()}  # answered, not open
    assert eid in {e["id"] for e in api.get("/escalations", params={"status": "answered"}).json()}
    r2 = api.post("/escalations", json={"answer_id": aid, "asked_by": "u2"}).json()
    closed = api.post(f"/escalations/{r2['escalation_id']}/close", json={"by": "owner"})
    assert closed.status_code == 200
    assert (
        api.post(f"/escalations/{r2['escalation_id']}/close", json={"by": "o"}).status_code == 409
    )
    assert api.post("/escalations", json={"answer_id": 999999, "asked_by": "u"}).status_code == 404
    rp = api.post(f"/answers/{aid}/report", json={"user_id": "u2", "note": "wrong"})
    assert rp.status_code == 201
    assert any(i["kind"] == "report" for i in api.get("/review-queue").json())


def test_conflicts_scan_queue_and_list(api: TestClient) -> None:
    r = api.post("/conflict-scan", json={})
    assert r.status_code == 202 and r.json()["queued"]
    assert api.post("/conflict-scan").json()["queued"] is False  # one waiting scan is enough
    with session_scope() as s:
        cur = next(f for f in fstore.get_facts(s) if "24 days" in f.statement)
        old = next(f for f in fstore.get_facts(s) if "20 days" in f.statement)
        cid = kb.add_conflict(
            s,
            subject_id=cur.subject_id,
            attribute=cur.attribute,
            scope={"client": "all"},
            fact_a=cur.id,
            fact_b=old.id,
            kind="value",
            authoritative_fact=cur.id,
            reason="v2 replaced v1",
        )
    rows = api.get("/conflicts").json()
    c = next(x for x in rows if x["id"] == cid)
    assert "24" in c["authoritative"]["value"] and "20" in c["conflicting"]["value"]
    assert c["reason"] == "v2 replaced v1"
    assert api.post(f"/conflicts/{cid}", json={"status": "resolved"}).status_code == 200
    assert cid not in {x["id"] for x in api.get("/conflicts").json()}
    assert api.post("/conflicts/999999", json={"status": "resolved"}).status_code == 404
    assert api.post(f"/conflicts/{cid}", json={"status": "bogus"}).status_code == 422


def test_tenant_header_isolates_reads(api: TestClient) -> None:
    eid = leave_entity(api)
    other = {"X-Tenant": "someone-else"}
    assert api.get("/entities", headers=other).json() == []
    assert api.get(f"/entities/{eid}", headers=other).status_code == 404
    assert api.get("/version", headers=other).json()["kb_version"] == 0
    assert api.get("/scopes", headers=other).json() == [{"key": "all", "label": "All clients"}]


def test_cors_allows_the_web_app(api: TestClient) -> None:
    r = api.options(
        "/ask",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    r = api.get("/version", headers={"Origin": "https://ps07-web.vercel.app"})
    assert r.headers.get("access-control-allow-origin") == "https://ps07-web.vercel.app"
    assert "x-kb-version" in r.headers.get("access-control-expose-headers", "").lower()
    r = api.get("/version", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in r.headers


def test_openapi_lists_every_endpoint(api: TestClient) -> None:
    paths = api.get("/openapi.json").json()["paths"]
    for p in [
        "/ask",
        "/episodes",
        "/episodes/upload",
        "/episodes/{episode_id}",
        "/episodes/{episode_id}/original",
        "/schema",
        "/schema/freeze",
        "/entities",
        "/entities/{entity_id}",
        "/entities/{entity_id}/timeline",
        "/entities/merge",
        "/entities/{entity_id}/split",
        "/facts",
        "/plugins",
        "/bindings",
        "/bindings/{binding_id}",
        "/calculate/{plugin}/{family}",
        "/context",
        "/changes",
        "/review-queue",
        "/review/{item_id}",
        "/escalations",
        "/escalations/{escalation_id}/reply",
        "/escalations/{escalation_id}/close",
        "/answers/{answer_id}/report",
        "/conflict-scan",
        "/conflicts",
        "/passages/{passage_id}",
        "/invoices",
        "/version",
        "/health",
    ]:
        assert p in paths, p
    assert api.get("/docs").status_code == 200


def test_rescan_keeps_owner_decisions_and_clears_what_is_gone(api: TestClient) -> None:
    with session_scope() as s:
        facts = fstore.get_facts(s)
        cur = next(f for f in facts if "24 days" in f.statement)
        old = next(f for f in facts if "20 days" in f.statement)
        other = next(f for f in facts if f.id not in (cur.id, old.id))
        kw = {"subject_id": cur.subject_id, "attribute": cur.attribute, "kind": "value"}
        a = kb.upsert_conflict(s, fact_a=cur.id, fact_b=old.id, reason="r1", **kw)
        b = kb.upsert_conflict(s, fact_a=cur.id, fact_b=other.id, reason="x", **kw)
        assert kb.upsert_conflict(s, fact_a=old.id, fact_b=cur.id, reason="r2", **kw) == a
        kb.set_conflict_status(s, a, "dismissed")
        assert kb.upsert_conflict(s, fact_a=cur.id, fact_b=old.id, reason="r3", **kw) == a
        assert kb.get_conflict(s, a).status == "dismissed"  # the owner's call survives a rescan
        assert kb.clear_conflicts_except(s, {a}) >= 1
        assert kb.get_conflict(s, b).status == "cleared"  # kept, not deleted
    assert b not in {c["id"] for c in api.get("/conflicts").json()}
    assert b in {c["id"] for c in api.get("/conflicts", params={"status": "cleared"}).json()}


def test_episode_counts_retry_and_metadata_correction(api: TestClient) -> None:
    eps = api.get("/episodes").json()
    built = [e for e in eps if e["passages"]]
    assert built and any(e["facts"] for e in built)
    src = next(s for e in built for s in e["sources"])
    assert {"id", "short_label", "doc_type", "dated", "status", "unsure"} <= set(src)
    assert api.post(f"/episodes/{built[0]['id']}/retry").status_code == 409  # not failed
    r = api.patch(f"/sources/{src['id']}", json={"by": "owner", "dated": "2026-01-15"})
    assert r.status_code == 200 and r.json()["updated"] == ["dated"] and r.json()["reresolve_job"]
    again = next(
        s for e in api.get("/episodes").json() for s in e["sources"] if s["id"] == src["id"]
    )
    assert again["dated"] == "2026-01-15" and again["confirmed_by"] == "owner"
    assert again["unsure"] == []
    assert api.patch("/sources/nope", json={"by": "o"}).status_code == 404


def test_stats_analytics_and_notifications(api: TestClient) -> None:
    st = api.get("/stats").json()
    assert st["documents"] >= 4 and st["passages"] > 0 and st["facts"] > 0 and st["entities"] > 0
    assert st["kb_version"] >= 1 and set(st["queue"]) == {"queued", "running", "failed"}
    api.post("/ask", json={"question": QUESTION, "user_id": "u9"})
    card = api.post("/ask", json={"question": "Is there a canteen subsidy?", "user_id": "u9"})
    an = api.get("/analytics").json()
    assert an["answers"] >= 2 and an["users"] >= 1 and an["latency_ms"]["p50"] is not None
    assert any("canteen" in u["question"] for u in an["unanswered"])
    assert an["top_sources"] and an["top_sources"][0]["label"]
    aid = int(card.json()["answer_id"])
    eid = api.post("/escalations", json={"answer_id": aid, "asked_by": "u9"}).json()[
        "escalation_id"
    ]
    api.post(f"/escalations/{eid}/reply", json={"expert_id": "x1", "text": "No subsidy."})
    notes = api.get("/notifications", params={"user_id": "u9"}).json()
    assert notes and "No subsidy" in notes[0]["body"] and notes[0]["answer_id"] == aid
    assert (
        api.post(f"/notifications/{notes[0]['id']}/read", json={"user_id": "u9"}).status_code == 200
    )
    assert api.get("/notifications", params={"user_id": "u9"}).json() == []
    assert (
        api.post(f"/notifications/{notes[0]['id']}/read", json={"user_id": "x"}).status_code == 404
    )


def test_schema_draft_edit_and_freeze(api: TestClient) -> None:
    before = api.get("/schema").json()["active"]
    d = api.post("/schema/draft", json={"by": "owner"})
    assert d.status_code == 201 and d.json()["created"]
    v = d.json()["version"]
    assert api.post("/schema/draft", json={"by": "owner"}).json() == {
        "version": v,
        "status": "draft",
        "created": False,
    }
    onto = dict(before["ontology"])
    onto["attributes"] = [
        {**a, "label": a["label"] + " (edited)"} if i == 0 else a
        for i, a in enumerate(onto["attributes"])
    ]
    assert api.put("/schema", json={"version": v, "ontology": onto}).status_code == 200
    assert (
        api.put("/schema", json={"version": before["version"], "ontology": onto}).status_code == 409
    )
    assert (
        api.put("/schema", json={"version": v, "ontology": {"attributes": "x"}}).status_code == 422
    )
    sc = api.get("/schema").json()
    assert sc["draft"]["version"] == v and sc["draft"]["ontology"]["attributes"][0][
        "label"
    ].endswith("(edited)")
    fr = api.post("/schema/freeze", json={"version": v, "by": "owner"})
    assert fr.status_code == 200, fr.text
    after = api.get("/schema").json()
    assert after["active"]["version"] == v and after["draft"] is None


def test_conflict_scan_status_and_open_in_review(api: TestClient) -> None:
    assert api.get("/conflict-scan").json() == {"status": "never"}
    api.post("/conflict-scan", json={})
    assert api.get("/conflict-scan").json()["status"] == "queued"
    with session_scope() as s:
        facts = fstore.get_facts(s)
        cur = next(f for f in facts if "24 days" in f.statement)
        old = next(f for f in facts if "20 days" in f.statement)
        cid = kb.add_conflict(
            s,
            subject_id=cur.subject_id,
            attribute=cur.attribute,
            fact_a=cur.id,
            fact_b=old.id,
            kind="value",
            authoritative_fact=cur.id,
            reason="v2 replaced v1",
        )
    r = api.post(f"/conflicts/{cid}/review", json={"by": "owner"})
    assert r.status_code == 201
    item = next(i for i in api.get("/review-queue").json() if i["id"] == r.json()["review_item"])
    assert item["kind"] == "conflict" and "24" in item["payload"]["authoritative"]["value"]
    assert api.post("/conflicts/999999/review", json={"by": "o"}).status_code == 404
