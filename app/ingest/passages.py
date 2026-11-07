"""Turn PassageDrafts into rows: stable ids, context headers, redaction."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.core.pack import Pack, SourceSpec
from app.core.redaction import redact_with_counts
from app.ingest.docx_parser import read_blocks
from app.ingest.segmenters import PassageDraft, segment_document

_DATE_VERB = {
    "sop": "effective",
    "desk_instruction": "updated",
    "client_memo": "issued",
    "faq": "last updated",
    "training_video": "recorded",
    "interview": "recorded",
    "shadowing": "observed",
}


@dataclass
class PassageRow:
    id: str
    source_id: str
    parent_id: str | None
    ordinal: int
    segment_kind: str
    locator: str
    heading_path: str
    section_title: str | None
    speaker: str | None
    text: str
    context_header: str
    client_scope: str
    valid_from: date | None
    valid_to: date | None
    source_status: str
    content_hash: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedCorpus:
    passages: list[PassageRow]
    source_meta: dict[str, dict[str, str]]


def fmt_date(d: date | None, month_only: bool = False) -> str:
    if d is None:
        return ""
    return f"{d:%b %Y}" if month_only else f"{d.day} {d:%b %Y}"


def display_locator(locator: str) -> str:
    return f"§{locator}" if re.fullmatch(r"\d+(?:\.\d+)*", locator) else locator


def passage_id(source_id: str, locator: str, occurrence: int) -> str:
    """Stable across re-ingestion: depends on position, not on the text."""
    return hashlib.sha1(f"{source_id}|{locator}|{occurrence}".encode()).hexdigest()[:20]


def context_header(draft: PassageDraft, src: SourceSpec, pack: Pack) -> str:
    label = src.label
    if src.version and src.version not in label:
        label = f"{label} v{src.version}"
    where = display_locator(draft.locator)
    title = draft.section_title or ""
    # "4.2 Price tolerance" -> "Price tolerance"; "4. Matching" -> "Matching"
    title = re.sub(rf"^{re.escape(draft.locator)}\.?\s+", "", title)
    if title and title not in draft.locator:
        where = (
            f"{where} {title}"
            if draft.segment_kind in ("section", "subsection", "section_parent", "table_row")
            else f"{where} · {title}"
        )
    # Transcript locators already start with the label ("Interview 1 [02:30]").
    parts = [where] if draft.locator.startswith(src.label) else [label, where]
    if draft.segment_kind == "table_row" and draft.meta.get("row_label"):
        parts.append(draft.meta["row_label"])
    verb = _DATE_VERB.get(src.kind, "dated")
    month_only = src.kind in ("training_video", "interview")
    if src.dated:
        parts.append(f"{verb} {fmt_date(src.dated, month_only)}")
    if src.status == "superseded":
        parts.append("superseded" + (f" after {fmt_date(src.valid_to)}" if src.valid_to else ""))
    elif src.valid_to:
        parts.append(f"valid until {fmt_date(src.valid_to)}")
    parts.append(f"status {src.status.replace('_', ' ')}")
    parts.append(pack.client_label(src.client_scope))
    return " · ".join(p for p in parts if p)


def _hash(*values: Any) -> str:
    blob = json.dumps(values, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def finalise(drafts: list[PassageDraft], pack: Pack) -> list[PassageRow]:
    rows: list[PassageRow] = []
    seen: Counter[tuple[str, str]] = Counter()
    first_id: dict[tuple[str, str], str] = {}
    ordinal_by_source: Counter[str] = Counter()

    for d in drafts:
        src = pack.sources[d.source_id]
        key = (d.source_id, d.locator)
        pid = passage_id(d.source_id, d.locator, seen[key])
        seen[key] += 1
        first_id.setdefault(key, pid)
        ordinal_by_source[d.source_id] += 1

        red = redact_with_counts(d.text)
        meta = dict(d.meta)
        if red.counts:
            meta["redactions"] = red.counts
        header = context_header(d, src, pack)
        parent = first_id.get((d.source_id, d.parent_locator)) if d.parent_locator else None
        rows.append(
            PassageRow(
                id=pid,
                source_id=d.source_id,
                parent_id=parent,
                ordinal=ordinal_by_source[d.source_id],
                segment_kind=d.segment_kind,
                locator=d.locator,
                heading_path=" > ".join(d.heading_path),
                section_title=d.section_title,
                speaker=d.speaker,
                text=red.text,
                context_header=header,
                client_scope=src.client_scope,
                valid_from=src.dated,
                valid_to=src.valid_to,
                source_status=src.status,
                content_hash=_hash(red.text, header, d.locator, d.segment_kind, parent, meta),
                meta=meta,
            )
        )
    return rows


def parse_corpus(pack: Pack, data_dir: Path) -> ParsedCorpus:
    drafts: list[PassageDraft] = []
    source_meta: dict[str, dict[str, str]] = {}
    for spec in pack.documents:
        path = data_dir / spec.file
        if not path.exists():
            raise FileNotFoundError(f"corpus file missing: {path}")
        parsed = segment_document(spec, read_blocks(path), pack)
        drafts.extend(parsed.passages)
        for sid, meta in parsed.source_meta.items():
            source_meta.setdefault(sid, {}).update(meta)
    return ParsedCorpus(passages=finalise(drafts, pack), source_meta=source_meta)
