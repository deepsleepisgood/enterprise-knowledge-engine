"""Replay: the history read per step, searching and showing sources as known at a past moment,
and a tenant-only job drain. Two hand-made versions of one rule: 2% (v1), then 1% (v2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import update

from app.core.db import session_scope
from app.store import entities, episodes, facts, history, jobs, search
from app.store.base import day_after, day_start, use_tenant
from app.store.models import Episode, Source

pytestmark = pytest.mark.db

T = "replay_t"
T0 = datetime(2026, 11, 10, 7, 0, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)  # the newer version arrives


def _source(s, ep: str, sid: str, label: str, dated: date, at: datetime, text: str) -> None:
    episodes.upsert_source(
        s,
        {
            "id": sid,
            "episode_id": ep,
            "title": label,
            "short_label": label,
            "doc_type": "sop",
            "status": "current",
            "dated": dated,
        },
    )
    episodes.upsert_passages(
        s,
        [
            {
                "id": f"{sid}-p",
                "source_id": sid,
                "episode_id": ep,
                "ordinal": 0,
                "segment_kind": "section",
                "locator": "4.2",
                "section_title": "Price tolerance",
                "text": text,
                "context_header": f"{label} · §4.2 Price tolerance",
                "content_hash": sid,
                "meta": {"leaf": True},
            }
        ],
    )
    s.execute(update(Episode).where(Episode.id == ep).values(created_at=at))
    s.execute(update(Source).where(Source.id == sid).values(created_at=at))


def _rule(s, sub: str, key: str, ep: str, sid: str, pct: float, at: datetime, **kw) -> int:
    return facts.insert(
        s,
        facts.NewFact(
            origin_key=key,
            subject_id=sub,
            attribute="price_tolerance.pct_of_line",
            value={"type": "percentage", "number": pct, "unit": "%"},
            statement=f"Price tolerance is {pct:g}% of the line value.",
            kind="rule",
            status="current",
            episode_id=ep,
            source_id=sid,
            passage_id=f"{sid}-p",
            **kw,
        ),
        at=at,
    )


@pytest.fixture
def two_versions(db):
    with use_tenant(T), session_scope() as s:
        episodes.delete_tenant_content(s)  # the db fixture resets the default tenant only
    with use_tenant(T), session_scope() as s:
        ep1, _ = episodes.add_episode(
            s, channel="upload", content_hash="v1", received_at=T0, source_uri="sop_v1.docx"
        )
        _source(s, ep1, "sop-v1", "SOP v1", date(2023, 7, 1), T0, "Tolerance is 2% of the line.")
        sub = entities.create(s, "policy", "Price tolerance")
        old = _rule(s, sub, "v1", ep1, "sop-v1", 2, T0 + timedelta(minutes=1))
    with use_tenant(T), session_scope() as s:
        ep2, _ = episodes.add_episode(
            s, channel="upload", content_hash="v2", received_at=T1, source_uri="sop_v2.docx"
        )
        _source(s, ep2, "sop-v2", "SOP v2", date(2026, 4, 1), T1, "Tolerance is 1% of the line.")
        # What linking the versions does: close v1 the day before v2 starts.
        episodes.update_source(s, "sop-v1", status="superseded", valid_until=date(2026, 3, 31))
        episodes.update_source(s, "sop-v2", supersedes_source_id="sop-v1")
        at = T1 + timedelta(minutes=1)
        retired = facts.revise(
            s, old, at=at, status="superseded", valid_to=day_after(date(2026, 3, 31))
        )
        new = _rule(s, sub, "v2", ep2, "sop-v2", 1, at, valid_from=day_start(date(2026, 4, 1)))
        facts.set_supersedes(s, new, retired)
    return {"ep1": ep1, "ep2": ep2}


def test_each_step_shows_what_it_changed_as_it_stood_then(two_versions) -> None:
    with use_tenant(T), session_scope() as s:
        steps = history.steps(s)
    assert [st.file for st in steps] == ["sop_v1.docx", "sop_v2.docx"]
    first, second = steps
    assert first.done_at == T1 - timedelta(microseconds=1)
    assert first.rules_in_force == 1 and first.replaced == []
    assert second.replaced_total == 1
    swap = second.replaced[0]
    assert (swap.old, swap.old_source, swap.new, swap.new_source) == (
        "2%",
        "SOP v1",
        "1%",
        "SOP v2",
    )
    assert second.rules_in_force == 1  # the 2% is superseded once v2 is in


def test_search_at_a_past_moment_only_sees_what_had_arrived(two_versions) -> None:
    after_v1 = T1 - timedelta(microseconds=1)
    with use_tenant(T), session_scope() as s:
        now = {pid for pid, _ in search.fulltext(s, "price tolerance", 10)}
        then = {pid for pid, _ in search.fulltext(s, "price tolerance", 10, known_at=after_v1)}
    assert now == {"sop-v2-p"}  # v1 is superseded and past its end date today
    assert then == {"sop-v1-p"}  # v2 had not arrived; v1 had no end date yet


def test_a_source_is_shown_as_it_was_before_its_newer_version_arrived(two_versions) -> None:
    with use_tenant(T), session_scope() as s:
        today = search.hydrate(s, ["sop-v1-p"])["sop-v1-p"]
        then = search.hydrate(s, ["sop-v1-p"], known_at=T1 - timedelta(seconds=1))["sop-v1-p"]
        later = search.hydrate(s, ["sop-v1-p"], known_at=T1 + timedelta(hours=1))["sop-v1-p"]
    assert (today.source_status, today.valid_until) == ("superseded", date(2026, 3, 31))
    assert (then.source_status, then.valid_until) == ("current", None)
    assert later.source_status == "superseded"


def test_a_drain_for_one_tenant_leaves_other_tenants_jobs(db) -> None:
    with use_tenant("other_t"), session_scope() as s:
        other = jobs.enqueue(s, "test_tenant_claim", {})
    with use_tenant(T), session_scope() as s:
        mine = jobs.enqueue(s, "test_tenant_claim", {})
    with session_scope() as s:
        got = jobs.claim(s, "w", ["test_tenant_claim"], tenant_id=T)
        assert got is not None and got.id == mine
        assert jobs.claim(s, "w", ["test_tenant_claim"], tenant_id=T) is None
        assert jobs.claim(s, "w", ["test_tenant_claim"]).id == other
