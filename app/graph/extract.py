"""Claim extraction: one MODEL_SMART structured call per passage, then strict post-processing.

The model proposes; code checks. Topic and parameter must come from the pack vocabulary
(or be marked as proposals), money is normalised to INR, interview and shadowing
passages always yield `practice` claims, and every quote is checked as a verbatim
substring of the passage. Domain guidance and few-shot examples come from
the pack (extraction.yaml).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.pack import Pack
from app.graph.schema import ClaimRec, ExtractedClaim, ExtractionResult

PROMPT_VERSION = "extract-v1"
PRACTICE_SOURCE_KINDS = {"interview", "shadowing"}
SYSTEM = """You extract rule-claims from one passage of an organisation's process documentation.
A claim is one checkable statement of a rule, threshold, procedure step, definition or working
practice. You return every claim the passage states, and nothing it does not state.

Rules:
- Use a topic and parameter from the vocabulary. If none fits, use topic or parameter "other"
  and put a short snake_case name in proposed_name.
- One claim per parameter value. A rule with a percentage and a fixed cap is two claims.
- A statement that something does not exist ("there is no tolerance") is a claim with
  number 0 and text "none".
- Percentages: 1% -> number 1, unit "%".
- If the passage records a change history (an old value and a new value), extract only the
  value this document states as current. Do not extract the old value.
- client is "all" unless the passage limits the claim to one client; then use the client key.
- kind: rule (what must be done), procedure (a step or sequence), definition, or practice
  (how an experienced person actually works, beyond what the rules say).
- quote: copy the exact words from the passage that state the claim. Do not paraphrase it.
- Ignore greetings, chit-chat and statements with no rule content. An empty list is fine.
"""


def system_prompt(pack: Pack) -> str:
    ex = pack.extraction
    parts = [SYSTEM]
    if ex.get("guidance"):
        parts.append("Domain guidance:\n" + ex["guidance"].strip())
    if ex.get("examples"):
        parts.append(ex["examples"].strip())
    return "\n\n".join(parts)


@dataclass
class PassageForExtraction:
    id: str
    source_id: str
    locator: str
    segment_kind: str
    context_header: str
    text: str


def vocabulary_text(pack: Pack) -> str:
    lines = []
    for topic, spec in pack.vocabulary.get("topics", {}).items():
        syn = ", ".join(spec.get("synonyms", []))
        lines.append(f"{topic}  ({syn})")
        for param, p in (spec.get("parameters") or {}).items():
            desc = f" — {p['description']}" if p.get("description") else ""
            lines.append(f"  {topic}.{param}: {p.get('type', 'text')}{desc}")
    return "\n".join(lines)


def build_prompt(p: PassageForExtraction, pack: Pack) -> str:
    clients = ", ".join(f"{k} ({c.name})" for k, c in pack.clients.items())
    return (
        f"Vocabulary:\n{vocabulary_text(pack)}\n\n"
        f"Client keys: all, {clients}\n\n"
        f"Passage ({p.context_header}):\n<<<\n{p.text}\n>>>"
    )


def _slug(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "unnamed").lower()).strip("_")[:60] or "unnamed"


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("‘", "'")).strip().lower()


def normalise_value(value: dict[str, Any], pack: Pack) -> dict[str, Any]:
    """Money in the pack's base currency; percentages in %; other units snake_case."""
    v = dict(value)
    unit = (v.get("unit") or "").strip().lower()
    units = {str(k).lower(): float(m) for k, m in pack.extraction.get("money_units", {}).items()}
    currency = pack.extraction.get("currency", "")
    if v.get("type") == "money" and v.get("number") is not None and unit in units:
        v["number"] = float(v["number"]) * units[unit]
        v["unit"] = currency
    elif v.get("type") == "percentage":
        v["unit"] = "%"
    elif unit:
        v["unit"] = unit.replace(" ", "_")
    return v


def claim_key(
    passage_id: str, index: int, topic: str, parameter: str, value: dict[str, Any]
) -> str:
    blob = json.dumps([passage_id, PROMPT_VERSION, index, topic, parameter, value], sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def postprocess(raw: ExtractedClaim, p: PassageForExtraction, pack: Pack, index: int) -> ClaimRec:
    src = pack.sources[p.source_id]
    topics = pack.vocabulary.get("topics", {})
    meta: dict[str, Any] = {
        "origin": "corpus",
        "prompt_version": PROMPT_VERSION,
        "quote": raw.quote,
    }

    topic, parameter = raw.topic, raw.parameter
    if topic not in topics:
        meta["proposed_topic"] = raw.proposed_name or topic
        topic, parameter = "other", _slug(raw.proposed_name or f"{topic}_{parameter}")
    elif parameter not in (topics[topic].get("parameters") or {}):
        meta["proposed_parameter"] = raw.proposed_name or parameter
        parameter = f"other_{_slug(raw.proposed_name or parameter)}"
    else:
        expected = topics[topic]["parameters"][parameter].get("type")
        if expected and expected != raw.value.type:
            meta["type_mismatch"] = {"expected": expected, "got": raw.value.type}

    meta["quote_verified"] = bool(raw.quote) and _squash(raw.quote) in _squash(p.text)

    client = src.client_scope
    if client == "all" and raw.client in pack.clients:
        client = raw.client

    kind = "practice" if src.kind in PRACTICE_SOURCE_KINDS else raw.kind
    value = normalise_value(raw.value.model_dump(), pack)
    return ClaimRec(
        key=claim_key(p.id, index, topic, parameter, value),
        topic=topic,
        parameter=parameter,
        client=client,
        value=value,
        kind=kind,
        statement=raw.statement,
        source_id=src.id,
        source_kind=src.kind,
        source_status=src.status,
        authority_rank=src.authority_rank,
        valid_at=src.dated,
        source_valid_to=src.valid_to,
        passage_id=p.id,
        condition=raw.condition,
        scope={"client": client, "materials": raw.materials},
        meta=meta,
    )


def extract_passage(
    p: PassageForExtraction,
    pack: Pack,
    structured_fn: Callable[..., ExtractionResult] | None = None,
) -> list[ClaimRec]:
    if structured_fn is None:
        from app.core.llm import structured

        structured_fn = structured
    result = structured_fn(
        build_prompt(p, pack),
        ExtractionResult,
        system=system_prompt(pack),
        model="smart",
        prompt_version=PROMPT_VERSION,
        max_tokens=8192,
    )
    return [postprocess(c, p, pack, i) for i, c in enumerate(result.claims)]
