"""Client scope of facts: declared scopes win, general sources that name one client go to it."""

from __future__ import annotations

from app.graph.scope import distinctive_words, fact_client, named_client

CLIENTS = ["Northwind Build Projects", "Northwind Foods", "Northwind Retail"]
KNOWN = distinctive_words(CLIENTS)


def test_distinctive_words_drop_the_shared_group_name() -> None:
    assert KNOWN["Northwind Build Projects"] == {"build", "projects"}
    assert KNOWN["Northwind Foods"] == {"foods"}
    assert named_client("The Retail cut-off is Friday", KNOWN) == "Northwind Retail"
    assert named_client("Northwind pays on Fridays", KNOWN) is None  # the group, not a client
    assert named_client("Foods and Retail both close early", KNOWN) is None  # ambiguous


def test_client_scoped_source_keeps_its_client() -> None:
    # extraction named the parent group inside the Retail memo: still the Retail memo's fact
    assert fact_client("Northwind Group", "", "Northwind Retail", KNOWN) == "Northwind Retail"
    assert fact_client(None, "rent invoices need a lease number", "Northwind Retail", KNOWN) == (
        "Northwind Retail"
    )
    # a memo may still state another known client's rule
    assert fact_client("Northwind Foods", "", "Northwind Retail", KNOWN) == "Northwind Foods"
    assert fact_client("Foods", "", "Northwind Retail", KNOWN) == "Northwind Foods"


def test_general_source_naming_one_client_is_scoped_to_it() -> None:
    assert fact_client(None, "Build Projects tolerance is five percent", "all", KNOWN) == (
        "Northwind Build Projects"
    )
    assert fact_client(None, "Tolerance is one percent", "all", KNOWN) is None
    assert fact_client("all clients", "Tolerance is one percent", None, KNOWN) is None
    assert (
        fact_client("Acme Ltd", "Acme pays late", None, KNOWN) == "Acme Ltd"
    )  # unknown: as stated
