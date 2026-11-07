"""Read a .docx body in document order as a flat list of typed blocks.

python-docx exposes paragraphs and tables separately; we walk the XML body so
tables stay in place next to the headings they belong to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

BlockKind = Literal["heading", "para", "list", "table"]

_HEADING_STYLE = re.compile(r"^Heading (\d)$")


@dataclass
class Block:
    kind: BlockKind
    text: str = ""
    level: int = 0  # heading level (1, 2, ...)
    rows: list[list[str]] = field(default_factory=list)  # tables only


def _clean(text: str) -> str:
    return re.sub(r"[ \t ]+", " ", text).strip()


def read_blocks(path: Path) -> list[Block]:
    document = docx.Document(str(path))
    blocks: list[Block] = []
    for el in document.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, document)
            text = _clean(p.text)
            if not text:
                continue
            style = p.style.name if p.style is not None else ""
            m = _HEADING_STYLE.match(style)
            if m:
                blocks.append(Block("heading", text, level=int(m.group(1))))
            elif style.startswith("List") or p._p.pPr is not None and p._p.pPr.numPr is not None:
                blocks.append(Block("list", text))
            else:
                blocks.append(Block("para", text))
        elif tag == "tbl":
            t = Table(el, document)
            rows = [[_clean(c.text.replace("\n", " / ")) for c in r.cells] for r in t.rows]
            blocks.append(Block("table", rows=rows))
    return blocks


def is_metadata_table(block: Block, metadata_keys: set[str]) -> bool:
    return (
        block.kind == "table"
        and bool(block.rows)
        and all(len(r) == 2 for r in block.rows)
        and all(r[0] in metadata_keys for r in block.rows)
    )


def table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""

    def fmt(r: list[str]) -> str:
        return "| " + " | ".join(c.replace("|", "\\|") for c in r) + " |"

    out = [fmt(rows[0]), "| " + " | ".join("---" for _ in rows[0]) + " |"]
    out.extend(fmt(r) for r in rows[1:])
    return "\n".join(out)


def render_blocks(blocks: list[Block]) -> str:
    """Render content blocks as plain text with Markdown lists and tables."""
    parts: list[str] = []
    list_buf: list[str] = []
    for b in blocks:
        if b.kind == "list":
            list_buf.append(f"- {b.text}")
            continue
        if list_buf:
            parts.append("\n".join(list_buf))
            list_buf = []
        if b.kind == "table":
            parts.append(table_to_markdown(b.rows))
        elif b.kind in ("para", "heading"):
            parts.append(b.text)
    if list_buf:
        parts.append("\n".join(list_buf))
    return "\n\n".join(parts)
