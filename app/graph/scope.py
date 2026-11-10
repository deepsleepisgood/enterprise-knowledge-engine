"""Client scope of a fact (BUILD_PLAN Phase 2: a client memo overrides the general rule for that
client only).

The known clients are the scopes the documents themselves declare (a memo "applies to Northwind
Retail" gets that `client_scope` at intake); nothing is configured per company. Two rules:

1. A fact from a client-scoped source belongs to that client, unless it names another known
   client. Entity resolution must not move it elsewhere (a subsidiary is not its parent group),
   so known clients are pinned by their exact name.
2. A fact from a general source (training, interview, FAQ) that names exactly one known client
   by a word only that client's name has ("the Retail cut-off is Friday") is that client's fact,
   not a rule for everyone.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

ALL = "all"
_CORPORATE = {"ltd", "pvt", "limited", "private", "inc", "llc", "llp", "co", "company", "the"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def distinctive_words(clients: Iterable[str]) -> dict[str, set[str]]:
    """Words of each client's name that no other known client shares ('Northwind Build Projects'
    -> {'build', 'projects'} when 'Northwind Foods' is also known)."""
    names = sorted({c for c in clients if c and c != ALL})
    words = {c: _words(c) - _CORPORATE for c in names}
    out: dict[str, set[str]] = {}
    for c, ws in words.items():
        others = set().union(*(w for o, w in words.items() if o != c)) if len(words) > 1 else set()
        out[c] = ws - others
    return out


def named_client(text: str, known: dict[str, set[str]]) -> str | None:
    """The one known client the text names, if exactly one."""
    tw = _words(text)
    hits = [c for c, ws in known.items() if ws and ws & tw]
    return hits[0] if len(hits) == 1 else None


_GENERAL = re.compile(r"\b(general|all clients|every client|in general)\b", re.I)


def fact_client(
    stated: str | None,
    text: str,
    source_scope: str | None,
    known: dict[str, set[str]],
    infer: bool = True,
    condition: str | None = None,
) -> str | None:
    """The client a fact belongs to, or None for every client.

    `stated` is what extraction said, `text` the fact's own words (statement and condition),
    `source_scope` the source's declared client scope. `infer=False` turns rule 2 off: for a
    source that outranks the client memos (the general rulebook), a client named in a fact is
    an example, not the fact's scope. A condition that calls the fact general also keeps it
    general."""
    scoped_source = source_scope if source_scope and source_scope != ALL else None
    stated = (stated or "").strip() or None
    if stated and stated.lower() in (ALL, "general", "none", "any", "all clients"):
        stated = None
    if stated:
        if stated in known:
            return stated
        mapped = named_client(stated, known)
        if mapped:
            return mapped
        # An unknown name inside a client-scoped source is that source's client (the parent
        # group named in a subsidiary's memo); elsewhere it stays as stated.
        return scoped_source or stated
    if scoped_source:
        return scoped_source
    if not infer or _GENERAL.search(condition or ""):
        return None
    return named_client(text, known)


def infers_scope(source_rank: int, client_source_ranks: list[int]) -> bool:
    """Rule 2 applies to sources ranked below the best client-scoped source."""
    return bool(client_source_ranks) and source_rank > min(client_source_ranks)
