"""Phase 0 acceptance: bitemporal store, job queue and worker, tenant column, dedupe."""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import inspect, text

from app.core.db import get_engine, session_scope
from app.store import entities, episodes, facts, jobs, kb
from app.store.base import day_after, day_start, last_day, use_tenant

pytestmark = pytest.mark.db

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_every_table_has_tenant_id(db) -> None:
    insp = inspect(get_engine())
    tables = [t for t in insp.get_table_names() if t != "alembic_version"]
    assert len(tables) >= 17
    missing = [t for t in tables if "tenant_id" not in {c["name"] for c in insp.get_columns(t)}]
    assert not missing


def test_bitemporal_indexes_exist(db) -> None:
    with get_engine().connect() as c:
        names = set(c.execute(text("SELECT indexname FROM pg_indexes")).scalars())
    assert {"ix_facts_valid", "ix_facts_known", "ix_passages_embedding"} <= names


def _subject(s) -> str:
    return entities.create(s, "policy", "Price tolerance")


def test_bitemporal_query_on_hand_inserted_fact(db) -> None:
    """valid_on filters valid time; known_at filters transaction time; revise keeps history."""
    with session_scope() as s:
        sub = _subject(s)
        old = facts.insert(
            s,
            facts.NewFact(
                origin_key="p1:0",
                subject_id=sub,
                attribute="price_tolerance.pct_of_line",
                value={"type": "percentage", "number": 2},
                statement="2% of line value.",
                kind="rule",
                status="current",
                valid_from=day_start(date(2023, 7, 1)),
            ),
            at=T0,
        )
    t1 = T0 + timedelta(days=100)  # the newer document arrives
    with session_scope() as s:
        facts.revise(s, old, at=t1, status="superseded", valid_to=day_after(date(2026, 3, 31)))
        facts.insert(
            s,
            facts.NewFact(
                origin_key="p2:0",
                subject_id=sub,
                attribute="price_tolerance.pct_of_line",
                value={"type": "percentage", "number": 1},
                statement="1% of line value.",
                kind="rule",
                status="current",
                valid_from=day_start(date(2026, 4, 1)),
            ),
            at=t1,
        )
    with session_scope() as s:
        attr = "price_tolerance.pct_of_line"
        # Before anything was recorded: nothing.
        assert facts.get_facts(s, attribute=attr, known_at=T0 - timedelta(days=1)) == []
        # Now, valid on 1 Mar 2026: the v3.1 value, closed on 31 Mar 2026.
        (on_mar,) = facts.get_facts(s, attribute=attr, valid_on=date(2026, 3, 1))
        assert on_mar.value["number"] == 2 and on_mar.status == "superseded"
        assert last_day(on_mar.valid_to) == date(2026, 3, 31)
        # Now, valid today: the new value.
        (today,) = facts.get_facts(s, attribute=attr, valid_on=date(2026, 11, 7))
        assert today.value["number"] == 1
        # As known before the newer document: the old value with an open interval.
        (then,) = facts.get_facts(
            s, attribute=attr, valid_on=date(2026, 11, 7), known_at=T0 + timedelta(days=50)
        )
        assert then.value["number"] == 2 and then.valid_to is None and then.status == "current"
        # Rows only grow: 3 rows, 2 live.
        assert facts.total_rows(s) == 3 and facts.count_live(s) == 2
        assert entities.get(s, sub).name == "Price tolerance"


def test_revise_requires_live_row(db) -> None:
    with session_scope() as s:
        sub = _subject(s)
        fid = facts.insert(
            s,
            facts.NewFact(
                origin_key="x",
                subject_id=sub,
                attribute="a",
                value={},
                statement="s",
                kind="rule",
                status="current",
            ),
        )
        facts.revise(s, fid, status="superseded")
        with pytest.raises(ValueError):
            facts.revise(s, fid, status="current")


def test_scope_filter(db) -> None:
    with session_scope() as s:
        sub = _subject(s)
        for i, client in enumerate([None, "Infra"]):
            facts.insert(
                s,
                facts.NewFact(
                    origin_key=f"s{i}",
                    subject_id=sub,
                    attribute="qty.pct",
                    value={"number": i},
                    statement="s",
                    kind="rule",
                    status="current",
                    scope={"client": client} if client else {},
                ),
            )
        assert len(facts.get_facts(s, attribute="qty.pct", scope={"client": "Infra"})) == 1
        assert len(facts.get_facts(s, attribute="qty.pct", scope={"client": None})) == 1


def test_episode_dedupe_counts_confirmations(db) -> None:
    now = datetime.now(UTC)
    with session_scope() as s:
        a, created = episodes.add_episode(s, channel="email", content_hash="h1", received_at=now)
        b, again = episodes.add_episode(s, channel="email", content_hash="h1", received_at=now)
        assert created and not again and a == b
        assert episodes.get_episode(s, a).confirmations == 1


def test_tenants_are_isolated(db) -> None:
    now = datetime.now(UTC)
    with session_scope() as s:
        episodes.add_episode(s, channel="api", content_hash="same", received_at=now)
        with use_tenant("other"):
            _, created = episodes.add_episode(
                s, channel="api", content_hash="same", received_at=now
            )
            assert created and len(episodes.list_episodes(s)) == 1
        assert len(episodes.list_episodes(s)) == 1
        with use_tenant("other"):
            episodes.delete_tenant_content(s)


def test_entity_alias_and_candidates(db) -> None:
    with session_scope() as s:
        eid = entities.create(s, "client", "Northwind Builders Ltd")
        entities.add_alias(s, eid, "Northwind")
        assert entities.by_alias(s, "northwind") == eid
        assert entities.by_alias(s, "NORTHWIND BUILDERS LTD.") == eid
        cands = entities.candidates(s, "Northwind Builders", "client")
        assert cands and cands[0].id == eid
        other = entities.create(s, "client", "Contoso Retail")
        entities.merge(s, eid, other)
        assert entities.by_alias(s, "Contoso Retail") == eid


def test_kb_version_and_change(db) -> None:
    with session_scope() as s:
        v = kb.bump_kb_version(s, "first")
        kb.record_change(s, v, "price tolerance 2% -> 1%")
        assert kb.current_kb_version(s) == v
        assert [c.summary for c in kb.changes_since(s, v - 1)] == ["price tolerance 2% -> 1%"]


# ---------------------------------------------------------------- job queue


def test_job_runs_through_worker(db) -> None:
    from app import worker

    seen: list[dict] = []
    worker.HANDLERS["test_echo"] = lambda payload: seen.append(payload) or {"ok": True}
    with session_scope() as s:
        jid = jobs.enqueue(s, "test_echo", {"n": 1})
    assert worker.drain(kinds=["test_echo"]) == 1
    assert seen == [{"n": 1}]
    with session_scope() as s:
        assert s.execute(text("SELECT status FROM jobs WHERE id=:i"), {"i": jid}).scalar() == "done"


def test_failed_job_retries_then_fails(db) -> None:
    from app import worker

    calls = []

    def boom(payload):
        calls.append(1)
        raise RuntimeError("nope")

    worker.HANDLERS["test_boom"] = boom
    with session_scope() as s:
        jid = jobs.enqueue(s, "test_boom", {}, max_attempts=2)
    worker.drain(kinds=["test_boom"])
    with session_scope() as s:
        row = s.execute(
            text("SELECT status, attempts, error, run_after > now() FROM jobs WHERE id=:i"),
            {"i": jid},
        ).one()
        assert row[0] == "queued" and row[1] == 1 and "nope" in row[2] and row[3]
        s.execute(text("UPDATE jobs SET run_after = now() WHERE id=:i"), {"i": jid})
    worker.drain(kinds=["test_boom"])
    with session_scope() as s:
        assert (
            s.execute(text("SELECT status FROM jobs WHERE id=:i"), {"i": jid}).scalar() == "failed"
        )
        assert [j.id for j in jobs.failed_jobs(s)] == [jid]
    assert len(calls) == 2


def test_skip_locked_never_double_claims(db) -> None:
    with session_scope() as s:
        for i in range(20):
            jobs.enqueue(s, "test_claim", {"i": i})
    claimed: list[int] = []
    lock = threading.Lock()

    def grab(w: int) -> None:
        while True:
            with session_scope() as s:
                job = jobs.claim(s, f"w{w}", ["test_claim"])
                if job is None:
                    return
                jobs.complete(s, job.id)
            with lock:
                claimed.append(job.id)

    ts = [threading.Thread(target=grab, args=(i,)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(claimed) == 20 and len(set(claimed)) == 20


def test_stale_running_job_is_requeued(db) -> None:
    with session_scope() as s:
        jid = jobs.enqueue(s, "test_stale", {})
        job = jobs.claim(s, "dead-worker", ["test_stale"])
        assert job and job.id == jid
        s.execute(
            text("UPDATE jobs SET locked_at = now() - interval '1 hour' WHERE id=:i"), {"i": jid}
        )
        assert jobs.requeue_stale(s, older_than_s=60) == 1
        assert jobs.claim(s, "w", ["test_stale"]).id == jid


def test_delete_episodes_removes_only_what_they_produced(db) -> None:
    """Test uploads can be removed from a dev graph without touching anything else."""
    now = datetime(2026, 11, 8, tzinfo=UTC)
    with use_tenant("purge"), session_scope() as s:
        keep_ep, _ = episodes.add_episode(s, channel="upload", content_hash="keep", received_at=now)
        drop_ep, _ = episodes.add_episode(s, channel="upload", content_hash="drop", received_at=now)
        for ep, sid in ((keep_ep, "src-keep"), (drop_ep, "src-drop")):
            episodes.upsert_source(
                s,
                {
                    "id": sid,
                    "episode_id": ep,
                    "title": sid,
                    "short_label": sid,
                    "doc_type": "memo",
                    "status": "current",
                },
            )
        shared = entities.create(s, "policy", "Visitor parking")
        only_drop = entities.create(s, "policy", "Smoke test")

        def add(key: str, sub: str, ep: str, sid: str, n: int) -> int:
            return facts.insert(
                s,
                facts.NewFact(
                    origin_key=key,
                    subject_id=sub,
                    attribute="parking.hours",
                    value={"type": "number", "number": n},
                    statement=f"{n} hours",
                    kind="rule",
                    status="current",
                    episode_id=ep,
                    source_id=sid,
                ),
            )

        kept = add("k", shared, keep_ep, "src-keep", 2)
        dropped = add("d", shared, drop_ep, "src-drop", 3)
        add("d2", only_drop, drop_ep, "src-drop", 1)
        kb.add_conflict(
            s, fact_a=kept, fact_b=dropped, kind="value", authoritative_fact=kept, reason="r"
        )
        kb.add_review_item(s, "metadata", {"source_id": "src-drop"})
        kb.add_review_item(s, "metadata", {"source_id": "src-keep"})
        draft = kb.save_schema(s, {"topics": []}, mode="induced")

    with use_tenant("purge"), session_scope() as s:
        out = episodes.delete_episodes(s, [drop_ep])
        assert out["facts"] == 2 and out["conflicts"] == 1 and out["review_items"] == 1
        assert out["entities"] == 1  # "Smoke test" had nothing else; "Visitor parking" stays
        assert kb.discard_schema_draft(s, draft)
    with use_tenant("purge"), session_scope() as s:
        assert [e.id for e in episodes.list_episodes(s)] == [keep_ep]
        assert [f.id for f in facts.get_facts(s, attribute="parking.hours")] == [kept]
        assert entities.get(s, shared) is not None and entities.get(s, only_drop) is None
        assert [r.payload["source_id"] for r in kb.list_review_items(s)] == ["src-keep"]
        assert kb.get_schema(s, draft) is None
    with session_scope() as s:  # other tenants untouched
        assert episodes.get_episode(s, keep_ep) is None
