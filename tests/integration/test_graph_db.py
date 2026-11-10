"""Phase 2 write path against the database, with a fake extractor (no network).

Small synthetic documents (a leave policy in two versions, a client memo, an interview) go
through the real ingestion, extraction post-processing, entity resolution, authority resolution
and bitemporal writes. TEST_PLAN level 3 checks on the shape of the graph.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pytest

from app import worker
from app.core.config import get_settings
from app.core.db import session_scope
from app.graph import pipeline as gp
from app.graph.compare import deterministic
from app.graph.extract import XFact, XResult, XValue
from app.graph.ontology import Attribute, Ontology, SourceRank, Topic
from app.graph.rules import RuleNotFound, expert_tips, get_rule
from app.ingest import pipeline as ip
from app.ingest.connectors import from_text
from app.ingest.intake import submit
from app.store import entities, kb
from app.store import facts as fstore

pytestmark = pytest.mark.db

ONTO = Ontology(
    name="test",
    base_currency="EUR",
    units={"k": 1000},
    topics=[Topic(key="annual_leave", label="Annual leave", synonyms=["holiday"])],
    attributes=[
        Attribute(
            key="annual_leave.days",
            topic="annual_leave",
            label="days per year",
            value_type="days",
            unit="days",
        ),
        Attribute(
            key="annual_leave.cash_cap",
            topic="annual_leave",
            label="cash-out cap",
            value_type="money",
            unit="EUR",
        ),
    ],
    source_ranking=[
        SourceRank(doc_type="memo", rank=1),
        SourceRank(doc_type="policy", rank=2),
        SourceRank(doc_type="interview", rank=5, practice=True),
    ],
)

V1 = """# Leave Policy — version 1

| Document | Leave Policy |
| --- | --- |
| Version | 1.0 |
| Effective | 1 January 2025 |

## 1. Annual leave

Staff get 20 days of annual leave a year.
"""
V2 = V1.replace("version 1", "version 2").replace("| 1.0 |", "| 2.0 |").replace(
    "1 January 2025", "1 January 2026"
).replace("20 days", "24 days") + (
    "\n## 2. Cash out\n\nUnused leave can be cashed out up to 2 k per year.\n"
)
MEMO = """# Part A — Memo M-1 (Northwind Builders)

| Issued | 1 March 2026 |
| --- | --- |
| From | HR Director, Northwind Builders |
| Valid until | 31 December 2026 |

Northwind Builders staff get 30 days of annual leave a year.

# Part B — Memo M-2 (Contoso)

| Issued | 2 March 2026 |
| --- | --- |
| From | HR, Contoso |

Contoso staff follow the policy.
"""
INTERVIEW = """# Expert interview 1 — Asha, HR lead

| Recorded | 5 May 2026 |
| --- | --- |
| Interviewer | Knowledge team |

[00:30] Interviewer: Any tips?

[00:40] Asha: Most people take 22 days, they save the rest for the cash-out.

# Expert interview 2 — Ravi

| Recorded | 6 May 2026 |
| --- | --- |
| Interviewer | Knowledge team |

[00:10] Ravi: Nothing to add.
"""


def fake_structured(prompt, schema, **kw):
    if schema is XResult:
        text = prompt.split("\nPassage:\n", 1)[1]
        facts = []
        m = re.search(r"(Northwind Builders staff )?get (\d+) days", text)
        if m:
            facts.append(
                XFact(
                    attribute="annual_leave.days",
                    value=XValue(
                        type="days",
                        number=float(m.group(2)),
                        unit="days",
                        text=f"{m.group(2)} days",
                    ),
                    client="Northwind Builders Ltd" if m.group(1) else None,
                    kind="rule",
                    statement=f"Staff get {m.group(2)} days.",
                    quote=m.group(0),
                )
            )
        if "cashed out up to 2 k" in text:
            facts.append(
                XFact(
                    attribute="annual_leave.cash_cap",
                    value=XValue(type="money", number=2, unit="k", text="2 k"),
                    kind="rule",
                    statement="Cash-out cap is 2k.",
                    quote="cashed out up to 2 k",
                )
            )
        if "take 22 days" in text:
            facts.append(
                XFact(
                    attribute="annual_leave.days",
                    value=XValue(type="days", number=22, unit="days", text="22 days"),
                    kind="practice",
                    statement="People take 22 days.",
                    quote="take 22 days",
                )
            )
        return XResult(facts=facts)
    return schema.model_validate({"same": False, "reason": "test"})


@pytest.fixture
def graph(db, monkeypatch, tmp_path):
    monkeypatch.setattr(ip, "_llm_structured", lambda: None)
    monkeypatch.setattr(gp, "_default_structured", lambda: fake_structured)
    monkeypatch.setattr(get_settings(), "blob_dir", tmp_path / "blobs")
    with session_scope() as s:
        kb.save_schema(s, ONTO.model_dump(), "induced", frozen_by="test")

    def ingest(text: str, name: str) -> str:
        with session_scope() as s:
            eid, _ = submit(s, from_text(text, channel="upload"))
            s.execute(
                __import__("sqlalchemy").text("UPDATE episodes SET source_uri=:n WHERE id=:i"),
                {"n": name, "i": eid},
            )
        worker.drain(kinds=["parse_episode"])
        return eid

    def build(eid: str | None = None) -> dict:
        return gp.extract_and_publish(
            eid, structured_fn=fake_structured, compare=deterministic, embed_fn=None
        )

    return ingest, build


def test_versions_memo_and_practice(graph) -> None:
    ingest, build = graph
    for text, name in [
        (V1, "leave_v1.md"),
        (V2, "leave_v2.md"),
        (MEMO, "memos.md"),
        (INTERVIEW, "interviews.md"),
    ]:
        ingest(text, name)
    out = build()
    assert not out["failures"]
    today = date(2026, 6, 1)
    with session_scope() as s:
        cur = get_rule(s, ONTO, "annual_leave", "days", today=today)
        assert cur.number == 24 and cur.status == "current" and cur.locator == "1"
        # Client memo overrides for its client only; name variants resolve to one entity.
        nw = get_rule(s, ONTO, "annual_leave", "days", client="Northwind Builders", today=today)
        assert nw.number == 30 and nw.client == "Northwind Builders Ltd"
        assert get_rule(s, ONTO, "annual_leave", "days", client="Contoso", today=today).number == 24
        # Memo expired after 31 Dec 2026: the general rule applies.
        later = get_rule(
            s, ONTO, "annual_leave", "days", client="Northwind Builders", today=date(2027, 1, 1)
        )
        assert later.number == 24
        # As of a day in 2025: version 1 was in force.
        old = get_rule(s, ONTO, "annual_leave", "days", as_of=date(2025, 6, 1))
        assert old.number == 20 and old.status == "superseded"
        assert old.valid_until == date(2025, 12, 31)
        # Money in base units via the schema's unit words.
        assert get_rule(s, ONTO, "annual_leave", "cash_cap", today=today).number == 2000
        # Practice is a tip, never the rule.
        tips = expert_tips(s, "annual_leave.days")
        assert [t.number for t in tips] == [22]
        # Before anything was recorded, nothing was known.
        with pytest.raises(RuleNotFound):
            get_rule(
                s,
                ONTO,
                "annual_leave",
                "days",
                today=today,
                known_at=datetime.now(UTC) - timedelta(days=1),
            )
        conflicts = kb.list_conflicts(s)
        assert any(c.kind == "practice_vs_rule" for c in conflicts)


def test_a_rule_dropped_by_the_next_version_ends_with_its_document(graph) -> None:
    """v1 has a cash-out cap that v2 leaves out. Until the owner retires v1's facts they stay
    open, but v1 ended on 31 Dec 2025, so its cap is not the rule in force after that."""
    ingest, build = graph
    cash = "\n## 2. Cash out\n\nUnused leave can be cashed out up to 2 k per year.\n"
    v2 = (
        V1.replace("version 1", "version 2")
        .replace("| 1.0 |", "| 2.0 |")
        .replace("1 January 2025", "1 January 2026")
    )
    # v1 is published before v2 arrives (as in a live feed), so its facts start open.
    assert not build(ingest(V1 + cash, "leave_v1.md"))["failures"]
    assert not build(ingest(v2, "leave_v2.md"))["failures"]
    with session_scope() as s:
        assert get_rule(s, ONTO, "annual_leave", "cash_cap", as_of=date(2025, 6, 1)).number == 2000
        with pytest.raises(RuleNotFound):
            get_rule(s, ONTO, "annual_leave", "cash_cap", today=date(2026, 6, 1))


def test_rebuild_is_idempotent_and_rows_only_grow(graph) -> None:
    ingest, build = graph
    ingest(V1, "v1.md")
    ingest(V2, "v2.md")
    first = build()
    with session_scope() as s:
        rows, version = fstore.total_rows(s), kb.current_kb_version(s)
    second = build()
    assert second["inserted"] == second["revised"] == second["retired"] == 0
    assert second["kb_version"] is None and first["kb_version"] is not None
    with session_scope() as s:
        assert fstore.total_rows(s) == rows and kb.current_kb_version(s) == version


def test_out_of_order_arrival_and_known_at(graph) -> None:
    """The newer version arrives first; when the old one lands, it does not take over."""
    ingest, build = graph
    e2 = ingest(V2, "v2.md")
    build(e2)
    with session_scope() as s:
        assert get_rule(s, ONTO, "annual_leave", "days", today=date(2026, 6, 1)).number == 24
    before_old = datetime.now(UTC)
    e1 = ingest(V1, "v1.md")  # links versions and queues re-resolution of the older source
    build(e1)
    worker.drain(kinds=["reresolve_source"])
    with session_scope() as s:
        assert get_rule(s, ONTO, "annual_leave", "days", today=date(2026, 6, 1)).number == 24
        assert get_rule(s, ONTO, "annual_leave", "days", as_of=date(2025, 6, 1)).number == 20
        # As known before v1 arrived, 2025 had no rule at all.
        with pytest.raises(RuleNotFound):
            get_rule(s, ONTO, "annual_leave", "days", as_of=date(2025, 6, 1), known_at=before_old)
        topic = entities.by_alias(s, "annual_leave", "topic")
        assert topic is not None
