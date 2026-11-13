"""Fact extraction (BUILD_PLAN Phase 2b): one passage -> entity mentions and typed facts.

MODEL_SMART reads the passage, its context header and the frozen ontology. Code then validates
attributes against the ontology (unknown ones become `other:<name>`), converts unit words with
the ontology's multipliers, checks the quote is in the passage, forces `practice` for practice
sources, and resolves the fact's validity interval from its own dates or its source's.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.graph.ontology import Ontology, ValueType

PROMPT_VERSION = "facts-v2"
Kind = Literal["rule", "practice", "definition", "procedure", "attribute"]


class XValue(BaseModel):
    type: ValueType
    number: float | None = Field(None, description="The number as written, in `unit`. 1% -> 1")
    unit: str | None = Field(
        None,
        description="%, a currency or unit word as written "
        "(e.g. a word for a multiple), days, working_days, hours, ...",
    )
    text: str = Field(description="The value in the passage's words")
    items: list[str] | None = Field(None, description="For lists: the items")


class XFact(BaseModel):
    attribute: str = Field(
        description="An attribute key from the vocabulary, or other:<snake_name>"
    )
    about: str | None = Field(
        None,
        description="Only if the fact is about one specific named "
        "thing (a supplier, customer, person, system, code, form): its name",
    )
    about_type: str | None = Field(None, description="Entity type of `about`")
    value: XValue
    client: str | None = Field(
        None,
        description="The client or customer the fact is limited "
        "to, as named; null if it applies generally",
    )
    materials: list[str] | None = Field(None, description="Items or categories it is limited to")
    condition: str | None = Field(None, description="When it applies, if conditional")
    kind: Kind
    statement: str = Field(description="One plain sentence restating the fact")
    quote: str = Field(description="The exact words of the passage that state it, verbatim")
    effective_date: str | None = Field(
        None,
        description="ISO date the fact starts, only if the "
        "passage states one; resolve relative dates against the "
        "message date",
    )
    expiry_date: str | None = Field(None, description="ISO last day it applies, if stated")


class XMention(BaseModel):
    name: str
    type: str


class XResult(BaseModel):
    mentions: list[XMention] = Field(default_factory=list)
    facts: list[XFact] = Field(default_factory=list)


SYSTEM = """You extract facts from one passage of an organisation's documents into a knowledge graph.
A fact is one checkable statement: a rule, threshold, procedure step, definition, a property of a
named thing, or a working practice. Return every fact the passage states and nothing else.
- Use an attribute key from the vocabulary. If none fits, use other:<short_snake_name>.
- One fact per value. "the lower of 2% and 300" is two facts (a percentage and a cap).
- Numeric attributes must have value.number in the unit as written, and the unit word.
- client: only when the fact is limited to one named client or customer.
- kind: rule (must or must not), procedure (a step), definition, attribute (a property of a named
  thing), practice (what a person does or advises from experience).
- quote: copy the words exactly from the passage. Never invent a value.
- The header says the document's status and date: still extract outdated documents faithfully.
- A change log or comparison ("version 1 said X, version 2 says Y"): extract only the value this
  document puts in force; earlier values are facts of the earlier document, not of this one.

Example. Passage: "2.1 Annual leave — Staff get 24 days a year, or 18 days in the first year.
Requests over 10 days need the director." Facts: annual_leave.days_per_year (days, 24);
annual_leave.first_year_days (days, 18); annual_leave.director_approval_above_days (days, 10)."""


def build_prompt(header: str, text: str, onto: Ontology, message_date: date | None) -> str:
    types = ", ".join(t.name for t in onto.entity_types) or "any"
    when = f"\nMessage date: {message_date.isoformat()}" if message_date else ""
    return (
        f"Vocabulary (topic, then attributes):\n{onto.prompt_text()}\n\n"
        f"Entity types: {types}\n\nPassage header: {header}{when}\n\nPassage:\n{text}"
    )


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", re.sub(r"[^\w%'\" ]+", " ", s)).strip()


def quote_in(quote: str, text: str) -> bool:
    q = _norm(quote)
    return bool(q) and q in _norm(text)


def money_multiplier(unit: str, onto: Ontology) -> float | None:
    """The multiplier from a money amount's unit to the base currency, or None when unknown.

    The unit may name the multiple and the currency together ("thousand USD", "USD million",
    "thousand dollars"): the base currency code is dropped, plurals are singularised, and every
    remaining word must be a known unit word (multipliers multiply). A unit with
    any word the ontology does not know gives None (the amount is kept as written, never guessed).
    """
    unit = unit.strip().lower().rstrip(".")
    if not unit:
        return None
    base = (onto.base_currency or "").lower()
    if unit in onto.units:
        return onto.units[unit]
    if base and unit == base:
        return 1.0
    words = [w for w in re.split(r"[\s_\-]+", unit) if w]
    mult, rest = 1.0, []
    for w in words:
        if w == base:
            continue
        key = w if w in onto.units else (w[:-1] if w.endswith("s") and w[:-1] in onto.units else "")
        if not key:
            rest.append(w)
            continue
        mult *= onto.units[key]
    return mult if words and not rest else None


def normalise_value(v: XValue, onto: Ontology, value_type: str | None) -> dict[str, Any]:
    out = v.model_dump()
    out["type"] = value_type or v.type
    if out["type"] == "money" and v.number is not None:
        mult = money_multiplier(v.unit or "", onto)
        if mult is not None:
            out["number"] = v.number * mult
            out["unit"] = onto.base_currency or v.unit
            out["as_written"] = {"number": v.number, "unit": v.unit}
    if out["type"] == "percentage":
        out["unit"] = "%"
    return out


def _iso(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


@dataclass
class Draft:
    """A fact as extracted, before entity resolution."""

    origin_key: str
    attribute: str
    topic: str
    about: str | None
    about_type: str | None
    value: dict[str, Any]
    client: str | None
    scope: dict[str, Any]
    condition: str | None
    kind: str
    statement: str
    quote: str
    quote_verified: bool
    asserted_from: date | None
    asserted_to: date | None  # last day in force, inclusive
    passage_id: str
    source_id: str
    episode_id: str
    mentions: list[tuple[str, str]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def extract_passage(
    p: Any,
    src: Any,
    onto: Ontology,
    message_date: date | None = None,
    structured_fn: Callable[..., Any] | None = None,
) -> list[Draft]:
    if structured_fn is None:
        from app.core.llm import structured

        structured_fn = structured
    result: XResult = structured_fn(
        build_prompt(p.context_header, p.text, onto, message_date),
        XResult,
        system=SYSTEM,
        model="smart",
        prompt_version=PROMPT_VERSION,
        max_tokens=16384,
    )
    return postprocess(result, p, src, onto)


def postprocess(result: XResult, p: Any, src: Any, onto: Ontology) -> list[Draft]:
    practice_source = bool((src.meta or {}).get("practice")) or onto.rank_of(src.doc_type).practice
    mentions = [(m.name.strip(), m.type.strip().lower()) for m in result.mentions if m.name.strip()]
    out = []
    for i, f in enumerate(result.facts):
        attr = onto.attribute(f.attribute.strip())
        if attr is None:
            slug = re.sub(r"[^a-z0-9]+", "_", f.attribute.lower().removeprefix("other:")).strip("_")
            key, topic, vtype = f"other:{slug or 'fact'}", "other", None
        else:
            key, topic, vtype = attr.key, attr.topic, attr.value_type
        kind = "practice" if practice_source else f.kind
        client = (f.client or "").strip() or None
        if client and client.lower() in ("all", "general", "none", "any"):
            client = None
        if client is None and src.client_scope and src.client_scope != "all":
            client = src.client_scope
        asserted_from = _iso(f.effective_date) or src.dated
        asserted_to = _iso(f.expiry_date) or src.valid_until
        about = (f.about or "").strip() or None
        scope: dict[str, Any] = {}
        if client:
            scope["client"] = client
        if f.materials:
            scope["materials"] = sorted({m.strip() for m in f.materials if m.strip()})
        out.append(
            Draft(
                origin_key=f"{p.id}:{i}:{PROMPT_VERSION}",
                attribute=key,
                topic=topic,
                about=about,
                about_type=(f.about_type or "").strip().lower() or None if about else None,
                value=normalise_value(f.value, onto, vtype),
                client=client,
                scope=scope,
                condition=f.condition,
                kind=kind,
                statement=f.statement.strip(),
                quote=f.quote.strip(),
                quote_verified=quote_in(f.quote, p.text),
                asserted_from=asserted_from,
                asserted_to=asserted_to,
                passage_id=p.id,
                source_id=src.id,
                episode_id=p.episode_id,
                mentions=mentions,
                meta={"proposed": f.attribute} if attr is None else {},
            )
        )
    return merge_list_values(out)


LIST_TYPES = ("enum", "list")


def _items(v: dict[str, Any]) -> list[str]:
    return [str(x) for x in (v.get("items") or [])] or [str(v.get("text") or "")]


def merge_list_values(drafts: list[Draft]) -> list[Draft]:
    """One passage stating several values of one list-type attribute together ("runs on Tuesday
    and Friday") is one fact with all of them. Extractors sometimes return one fact per value;
    left apart, resolution would treat them as conflicting values and keep only one. Numbers are
    never merged (two numbers for one attribute in one passage is a real conflict)."""
    groups: dict[tuple, list[Draft]] = {}
    order: list[tuple] = []
    for d in drafts:
        if str(d.value.get("type")) not in LIST_TYPES:
            key: tuple = ("single", id(d))
        else:
            key = (
                d.attribute,
                (d.about or "").lower(),
                tuple(sorted((k, str(v)) for k, v in d.scope.items())),
                d.condition or "",
                d.kind,
            )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d)
    out = []
    for key in order:
        ds = groups[key]
        if len(ds) == 1:
            out.append(ds[0])
            continue
        items: list[str] = []
        for d in ds:
            for it in _items(d.value):
                if it and it.lower() not in {x.lower() for x in items}:
                    items.append(it)
        first = ds[0]
        text = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
        statements = list(dict.fromkeys(d.statement for d in ds if d.statement))
        quotes = list(dict.fromkeys(d.quote for d in ds if d.quote))
        first.value = {**first.value, "text": text, "items": items}
        first.statement = " ".join(statements)
        first.quote = " … ".join(quotes)
        first.quote_verified = all(d.quote_verified for d in ds)
        first.meta = {**first.meta, "merged_values": len(ds)}
        out.append(first)
    return out
