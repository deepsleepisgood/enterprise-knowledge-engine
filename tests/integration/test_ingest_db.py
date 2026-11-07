"""Migrations + ingestion against a real Postgres (pgvector)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, inspect, select, text

from app.core.config import get_settings
from app.core.models import Passage, Source, Vendor

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def first_run(database_url, pack):
    from app.core.db import session_scope
    from app.ingest.loader import ingest

    with session_scope() as s:  # start empty, whatever ran before in this test database
        s.execute(
            text(
                "TRUNCATE claims, conflicts, changes, kb_versions, passages, sources, vendors "
                "RESTART IDENTITY CASCADE"
            )
        )
    with session_scope() as s:
        report = ingest(s, pack, get_settings().data_dir)
    return report


def test_schema_has_all_tables(database_url) -> None:
    from app.core.db import get_engine

    tables = set(inspect(get_engine()).get_table_names())
    expected = {
        "sources",
        "episodes",
        "passages",
        "claims",
        "conflicts",
        "review_items",
        "kb_versions",
        "changes",
        "answers_log",
        "acks",
        "notifications",
        "tacit_entries",
        "vendors",
    }
    assert expected <= tables
    with get_engine().connect() as c:
        assert c.execute(text("select 1 from pg_extension where extname='vector'")).scalar() == 1


def test_first_ingest_loads_everything(first_run, corpus) -> None:
    assert first_run.sources == 14
    assert first_run.passages_inserted == len(corpus.passages)
    assert first_run.vendors == 650


def test_reingest_is_idempotent(first_run, pack) -> None:
    from app.core.db import session_scope
    from app.ingest.loader import ingest

    with session_scope() as s:
        before = s.scalar(select(func.count()).select_from(Passage))
        again = ingest(s, pack, get_settings().data_dir)
    with session_scope() as s:
        after = s.scalar(select(func.count()).select_from(Passage))
        dupes = s.execute(
            text(
                "select source_id, locator, text, count(*) from passages "
                "group by 1,2,3 having count(*) > 1"
            )
        ).all()
        sources = s.scalar(select(func.count()).select_from(Source))
        vendors = s.scalar(select(func.count()).select_from(Vendor))
    assert before == after == first_run.passages_total
    assert (again.passages_inserted, again.passages_updated, again.passages_deleted) == (0, 0, 0)
    assert again.passages_unchanged == before
    assert not dupes
    assert sources == 14 and vendors == 650


def test_full_text_search_finds_price_tolerance(first_run) -> None:
    from app.core.db import session_scope

    with session_scope() as s:
        rows = s.execute(
            text(
                "select source_id, locator from passages "
                "where tsv @@ plainto_tsquery('english', 'price tolerance') "
                "order by ts_rank(tsv, plainto_tsquery('english', 'price tolerance')) desc limit 5"
            )
        ).all()
    assert ("sop_v4", "4.2") in [tuple(r) for r in rows]


def test_vendor_table_has_no_sensitive_columns(database_url) -> None:
    from app.core.db import get_engine

    cols = {c["name"] for c in inspect(get_engine()).get_columns("vendors")}
    assert not {c for c in cols if any(k in c for k in ("pan", "bank", "ifsc", "account"))}


def test_vendor_fields_typed(first_run) -> None:
    from app.core.db import session_scope

    with session_scope() as s:
        v = s.get(Vendor, "V20000")
    assert v is not None and v.primary_client == "pharma"
    assert v.einvoice_required is True and v.aato_crore == pytest.approx(25.1)
    assert v.habit_note and "/A" in v.habit_note


def test_source_metadata_and_memo_scope(first_run) -> None:
    from app.core.db import session_scope

    with session_scope() as s:
        memo = s.get(Source, "cm_inf_02")
        scopes = set(
            s.scalars(select(Passage.client_scope).where(Passage.source_id == "cm_inf_02"))
        )
    assert memo.client_scope == "infra" and str(memo.valid_to) == "2027-03-31"
    assert memo.meta["From"] == "Financial Controller, Arvana Infra Projects"
    assert scopes == {"infra"}
