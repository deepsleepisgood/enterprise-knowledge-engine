"""Entity split (owner correction): a subsidiary wrongly filed under its parent group."""

from __future__ import annotations

import pytest

from app.core.db import session_scope
from app.graph.split import split_entity
from app.store import entities, facts
from app.store.base import use_tenant

pytestmark = pytest.mark.db


def _fact(s, key: str, subject: str, client_id: str, statement: str) -> int:
    return facts.insert(
        s,
        facts.NewFact(
            origin_key=key,
            subject_id=subject,
            attribute="rent.rule",
            value={"type": "text", "text": statement},
            statement=statement,
            kind="rule",
            status="current",
            scope={"client": "Northwind Group", "client_id": client_id},
        ),
    )


def test_split_moves_only_facts_that_name_the_alias(db) -> None:
    with use_tenant("split"), session_scope() as s:
        group = entities.create(s, "client", "Northwind Group")
        entities.add_alias(s, group, "Northwind Retail")  # the wrong merge
        topic = entities.create(s, "topic", "Rent")
        retail = _fact(
            s, "r", topic, group, "Store rent is a non-PO category for Northwind Retail."
        )
        _fact(s, "g", topic, group, "Northwind Group companies pay rent monthly.")

    with use_tenant("split"):
        out = split_entity(group, "Northwind Retail", ["Northwind Retail"], by="owner-1")
    assert out["moved_facts"] == 1

    with use_tenant("split"), session_scope() as s:
        new_id = out["entity_id"]
        assert entities.by_alias(s, "Northwind Retail", "client") == new_id
        assert entities.by_alias(s, "Northwind Group", "client") == group
        live = {f.statement: f.scope for f in facts.get_facts(s, attribute="rent.rule")}
        assert live["Store rent is a non-PO category for Northwind Retail."]["client_id"] == new_id
        assert live["Northwind Group companies pay rent monthly."]["client_id"] == group
        assert facts.total_rows(s) == 3  # the moved fact is a new version; the old row is kept
        assert retail not in {f.id for f in facts.get_facts(s, attribute="rent.rule")}
