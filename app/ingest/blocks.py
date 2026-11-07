"""The canonical block list every parser produces (SCOPE.md 3.5, layer 1).

Nothing downstream of the parsers may depend on the file format: segmentation, metadata
inference and extraction see only these blocks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

BlockType = Literal[
    "heading",
    "paragraph",
    "list_item",
    "table",
    "table_row",
    "turn",
    "quote",
    "figure",
    "header_footer",
]


@dataclass
class Block:
    type: BlockType
    text: str = ""
    level: int | None = None  # heading level (1 = top) or list nesting depth
    rows: list[list[str]] = field(default_factory=list)  # tables: first row is the header
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    time: str | None = None  # turns: the timestamp exactly as written ("04:30")
    time_style: str | None = None  # "bracket" for "[04:30]", "plain" for "10:05"
    speaker: str | None = None
    style: str | None = None  # source style name or tag ("Heading 2", "h3", "List Number")
    position: dict[str, Any] = field(default_factory=dict)  # slide, sheet, cells, offsets
    meta: dict[str, Any] = field(default_factory=dict)  # bold, font_size, notes, ...


@dataclass
class ParseResult:
    blocks: list[Block]
    tier: int  # 1 native, 2 converted legacy, 3 vision, 5 unknown
    quality: float  # 0..1 parse-quality score
    file_meta: dict[str, Any] = field(default_factory=dict)  # file properties, email headers
    notes: list[str] = field(default_factory=list)  # why quality is low, what escalated


def clean(text: str) -> str:
    return re.sub(r"[ \t\u00a0\u200b]+", " ", text).strip()


# "[04:30] Pallavi: text", "04:30 — text", "10:05 - L opens ...", "[1:02:03] Speaker: text"
_TURN = re.compile(
    r"^(?P<open>\[)?(?P<time>\d{1,2}:\d{2}(?::\d{2})?)(?(open)\])\s*"
    r"(?:[—–\-]\s*)?"
    r"(?:(?P<speaker>[A-Z][\w.'’\- ]{0,40}?):\s+)?"
    r"(?P<text>\S.*)$",
    re.S,
)


def detect_turns(blocks: list[Block]) -> list[Block]:
    """Turn timestamped paragraphs and list items into `turn` blocks (any format).

    A block becomes a turn only when it starts with a timestamp; the rest is unchanged.
    """
    out: list[Block] = []
    for b in blocks:
        if b.type in ("paragraph", "list_item") and b.text:
            m = _TURN.match(b.text)
            if m:
                out.append(
                    Block(
                        "turn",
                        text=m.group("text").strip(),
                        time=m.group("time"),
                        time_style="bracket" if m.group("open") else "plain",
                        speaker=(m.group("speaker") or "").strip() or None,
                        page=b.page,
                        style=b.style,
                        position=b.position,
                        meta=b.meta,
                    )
                )
                continue
        out.append(b)
    return out


def table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)

    def fmt(r: list[str]) -> str:
        cells = [c.replace("|", "\\|").replace("\n", " / ") for c in r] + [""] * (width - len(r))
        return "| " + " | ".join(cells) + " |"

    out = [fmt(rows[0]), "| " + " | ".join("---" for _ in range(width)) + " |"]
    out.extend(fmt(r) for r in rows[1:])
    return "\n".join(out)


def block_text(b: Block) -> str:
    """Plain-text rendering of one block, used for passage text."""
    if b.type == "table":
        return table_to_markdown(b.rows)
    if b.type == "turn":
        stamp = f"[{b.time}]" if b.time_style == "bracket" else (b.time or "")
        who = f"{b.speaker}: " if b.speaker else ""
        sep = " " if b.time_style == "bracket" else " — "
        return f"{stamp}{sep}{who}{b.text}".strip()
    if b.type == "list_item":
        return f"- {b.text}"
    if b.type == "quote":
        return f"> {b.text}"
    return b.text
