"""Structure-aware segmenters. Never fixed-size chunks.

Each segmenter turns a document's blocks into PassageDrafts with a locator that
matches how people cite the source: `4.2`, `Part A, step 4`, `Part C (CM-INF-02)`,
`Video 1 [04:30]`, `Shadowing 10:05`. Which segmenter runs on which file, and
which source each part belongs to, comes from the domain pack.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.pack import DocumentSpec, Pack
from app.ingest.docx_parser import Block, is_metadata_table, render_blocks


@dataclass
class PassageDraft:
    source_id: str
    locator: str
    segment_kind: str
    heading_path: list[str]
    section_title: str | None
    text: str
    speaker: str | None = None
    parent_locator: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    passages: list[PassageDraft]
    source_meta: dict[str, dict[str, str]]


class _Ctx:
    def __init__(self, pack: Pack) -> None:
        self.pack = pack
        self.metadata_keys = set(pack.metadata_keys)
        self.skip = [re.compile(p) for p in pack.skip_paragraphs]
        self.source_meta: dict[str, dict[str, str]] = {}

    def skipped(self, b: Block) -> bool:
        return b.kind == "para" and any(p.search(b.text) for p in self.skip)

    def is_meta(self, b: Block) -> bool:
        return is_metadata_table(b, self.metadata_keys)

    def add_meta(self, source_id: str, b: Block) -> None:
        self.source_meta.setdefault(source_id, {}).update({k: v for k, v in b.rows})

    def label(self, source_id: str) -> str:
        return self.pack.sources[source_id].label


# --- SOPs: numbered sections ------------------------------------------------------------

_SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")


@dataclass
class _Node:
    number: str
    heading: str
    blocks: list[Block] = field(default_factory=list)
    children: list[_Node] = field(default_factory=list)


def _row_text(header: list[str], row: list[str]) -> str:
    first = row[0]
    rest = "; ".join(f"{h}: {v}" for h, v in zip(header[1:], row[1:], strict=False))
    return f"{first} — {rest}" if rest else first


def numbered_sections(spec: DocumentSpec, blocks: list[Block], ctx: _Ctx) -> list[PassageDraft]:
    assert spec.source, "numbered_sections needs `source`"
    src = spec.source
    label = ctx.label(src)
    tops: list[_Node] = []
    current: _Node | None = None

    for b in blocks:
        if ctx.skipped(b):
            continue
        if b.kind == "heading":
            m = _SECTION_RE.match(b.text)
            if m:
                node = _Node(m.group(1), b.text)
                if "." in node.number and tops:
                    tops[-1].children.append(node)
                else:
                    tops.append(node)
                current = node
                continue
        if current is None:
            if ctx.is_meta(b):
                ctx.add_meta(src, b)
            continue  # title block / preamble
        current.blocks.append(b)

    out: list[PassageDraft] = []
    for top in tops:
        path = [label, top.heading]
        own = render_blocks(top.blocks)
        if top.number in spec.row_sections:
            table = next((b for b in top.blocks if b.kind == "table"), None)
            out.append(PassageDraft(src, top.number, "section", path, top.heading, own))
            if table and len(table.rows) > 1:
                header = table.rows[0]
                for row in table.rows[1:]:
                    out.append(
                        PassageDraft(
                            src,
                            top.number,
                            "table_row",
                            [*path, row[0]],
                            top.heading,
                            _row_text(header, row),
                            parent_locator=top.number,
                            meta={"row": dict(zip(header, row, strict=False)), "row_label": row[0]},
                        )
                    )
            continue
        if top.children:
            child_texts = [f"{c.heading}\n{render_blocks(c.blocks)}" for c in top.children]
            parent_text = "\n\n".join([t for t in [own] if t] + child_texts)
            out.append(
                PassageDraft(
                    src,
                    top.number,
                    "section_parent",
                    path,
                    top.heading,
                    parent_text,
                    meta={"parent": True},
                )
            )
            for c in top.children:
                text = render_blocks(c.blocks)
                if text:
                    out.append(
                        PassageDraft(
                            src,
                            c.number,
                            "subsection",
                            [*path, c.heading],
                            c.heading,
                            text,
                            parent_locator=top.number,
                        )
                    )
        elif own:
            out.append(PassageDraft(src, top.number, "section", path, top.heading, own))
    return out


# --- Desk instructions, memos, FAQ: lettered parts ---------------------------------------


def lettered_parts(spec: DocumentSpec, blocks: list[Block], ctx: _Ctx) -> list[PassageDraft]:
    assert spec.heading_pattern, "lettered_parts needs `heading_pattern`"
    pattern = re.compile(spec.heading_pattern)
    parts: list[tuple[str, str, str, list[Block]]] = []
    for b in blocks:
        if ctx.skipped(b):
            continue
        m = pattern.match(b.text) if b.kind == "heading" else None
        if m:
            parts.append((m.group("part"), b.text, m.group("title"), []))
        elif parts:
            parts[-1][3].append(b)

    out: list[PassageDraft] = []
    for key, heading, title, content_all in parts:
        cfg = spec.parts.get(key)
        if cfg is None:
            raise ValueError(f"{spec.file}: Part {key} has no entry in pack.yaml")
        src = cfg["source"]
        content: list[Block] = []
        for b in content_all:
            (ctx.add_meta(src, b) if ctx.is_meta(b) else content.append(b))
        path = [ctx.label(src), heading]
        style = cfg["style"]
        part_loc = f"Part {key}"

        if style == "steps":
            steps = [b.text for b in content if b.kind == "list"]
            intro = render_blocks([b for b in content if b.kind != "list"])
            numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
            out.append(
                PassageDraft(
                    src,
                    part_loc,
                    "part",
                    path,
                    title,
                    "\n\n".join(t for t in [intro, numbered] if t),
                    meta={"parent": True, "step_count": len(steps)},
                )
            )
            for i, step in enumerate(steps, 1):
                loc = f"{part_loc}, step {i}"
                out.append(
                    PassageDraft(
                        src,
                        loc,
                        "step",
                        [*path, f"Step {i}"],
                        title,
                        step,
                        parent_locator=part_loc,
                        meta={"step": i},
                    )
                )
        elif style == "whole":
            loc = cfg.get("locator", part_loc)
            out.append(
                PassageDraft(
                    src, loc, "memo", path, title, render_blocks(content), meta={"part": part_loc}
                )
            )
        elif style == "table_rows":
            loc = cfg.get("locator", part_loc)
            table = next((b for b in content if b.kind == "table"), None)
            if table is None or len(table.rows) < 2:
                raise ValueError(f"{spec.file}: Part {key} expected a table")
            header = table.rows[0]
            for row in table.rows[1:]:
                text = "\n".join(f"{h}: {v}" for h, v in zip(header, row, strict=False))
                out.append(
                    PassageDraft(
                        src,
                        loc,
                        "faq_row",
                        [*path, row[0]],
                        row[0],
                        text,
                        meta={"row": dict(zip(header, row, strict=False)), "part": part_loc},
                    )
                )
        else:
            raise ValueError(f"unknown part style {style!r}")
    return out


# --- Transcripts: timestamped turns and timed notes --------------------------------------

_TURN_RE = re.compile(r"^\[(\d{1,2}:\d{2})\]\s*([^:\[\]]{1,60}):\s*(.+)$", re.S)
_NOTE_RE = re.compile(r"^(\d{1,2}:\d{2})\s*[—–-]\s*(.+)$", re.S)


def transcripts(spec: DocumentSpec, blocks: list[Block], ctx: _Ctx) -> list[PassageDraft]:
    matchers = [(re.compile(s["heading"]), s) for s in spec.sections]
    sections: list[tuple[dict[str, Any], str, list[Block]]] = []
    for b in blocks:
        if ctx.skipped(b):
            continue
        if b.kind == "heading":
            cfg = next((s for rx, s in matchers if rx.search(b.text)), None)
            if cfg is None:
                raise ValueError(f"{spec.file}: no pack section for heading {b.text!r}")
            sections.append((cfg, b.text, []))
        elif sections:
            sections[-1][2].append(b)

    questioners = set(spec.question_speakers)
    out: list[PassageDraft] = []
    for cfg, heading, content in sections:
        src, prefix = cfg["source"], cfg["prefix"]
        path = [ctx.label(src), heading]
        lines: list[Block] = []
        for b in content:
            (ctx.add_meta(src, b) if ctx.is_meta(b) else lines.append(b))

        if cfg["style"] == "timed_notes":
            for b in lines:
                m = _NOTE_RE.match(b.text)
                if not m:
                    raise ValueError(f"{prefix}: unparsed note {b.text[:60]!r}")
                ts, body = m.groups()
                out.append(
                    PassageDraft(
                        src,
                        f"{prefix} {ts}",
                        "note",
                        [*path, ts],
                        heading,
                        body.strip(),
                        meta={"time": ts},
                    )
                )
            continue

        pending: tuple[str, str, str] | None = None
        for b in lines:
            m = _TURN_RE.match(b.text)
            if not m:
                if out and out[-1].source_id == src:
                    out[-1].text += "\n" + b.text  # continuation of the previous turn
                    continue
                raise ValueError(f"{prefix}: unparsed turn {b.text[:60]!r}")
            ts, speaker, body = m.group(1), m.group(2).strip(), m.group(3).strip()
            if speaker in questioners:
                pending = (ts, speaker, body)
                continue
            text = f"{speaker}: {body}"
            meta: dict[str, Any] = {"timestamp": f"[{ts}]"}
            if pending:
                q_ts, q_speaker, q_body = pending
                text = f"{q_speaker} [{q_ts}]: {q_body}\n{text}"
                meta["question_timestamp"] = f"[{q_ts}]"
                pending = None
            out.append(
                PassageDraft(
                    src,
                    f"{prefix} [{ts}]",
                    "turn",
                    [*path, f"[{ts}]"],
                    heading,
                    text,
                    speaker=speaker,
                    meta=meta,
                )
            )
        if pending:
            q_ts, q_speaker, q_body = pending
            out.append(
                PassageDraft(
                    src,
                    f"{prefix} [{q_ts}]",
                    "turn",
                    [*path, f"[{q_ts}]"],
                    heading,
                    f"{q_speaker}: {q_body}",
                    speaker=q_speaker,
                    meta={"timestamp": f"[{q_ts}]"},
                )
            )
    return out


SEGMENTERS: dict[str, Callable[[DocumentSpec, list[Block], _Ctx], list[PassageDraft]]] = {
    "numbered_sections": numbered_sections,
    "lettered_parts": lettered_parts,
    "transcripts": transcripts,
}


def segment_document(spec: DocumentSpec, blocks: list[Block], pack: Pack) -> ParsedDocument:
    fn = SEGMENTERS.get(spec.segmenter)
    if fn is None:
        raise ValueError(f"unknown segmenter {spec.segmenter!r}")
    ctx = _Ctx(pack)
    passages = fn(spec, blocks, ctx)
    return ParsedDocument(passages=passages, source_meta=ctx.source_meta)
