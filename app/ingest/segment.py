"""Structure inference: canonical blocks -> documents -> passages (SCOPE.md 3.5, layer 2).

Evidence, in order: explicit headings (styles, tags, slide titles), visual signals (font size,
bold), numbering patterns as hints, and optionally an LLM structure-repair pass; a sliding window
is the last resort. Nothing here knows any company's document templates.

Splitting a file into several documents: when two or more top-level sections each open with a
key-value metadata table, every top-level section is its own document (a pack of memos, a set of
transcripts). Otherwise the file is one document.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.ingest.blocks import Block, block_text, table_to_markdown

# Generic document-metadata labels (any domain): what a header table calls its fields.
META_KEYS = {
    "document",
    "title",
    "subject",
    "name",
    "version",
    "rev",
    "revision",
    "edition",
    "effective",
    "effective from",
    "effective date",
    "date",
    "dated",
    "issued",
    "issue date",
    "updated",
    "last updated",
    "recorded",
    "published",
    "approved",
    "approved by",
    "owner",
    "author",
    "prepared by",
    "issued by",
    "from",
    "to",
    "presenter",
    "speaker",
    "interviewer",
    "observer",
    "shadowed",
    "status",
    "valid until",
    "valid till",
    "expires",
    "expiry",
    "review date",
    "replaces",
    "supersedes",
    "reference",
    "ref",
    "document id",
    "doc id",
    "id",
    "applies to",
    "scope",
    "audience",
    "department",
    "client",
    "length",
    "duration",
    "used in",
    "context",
    "classification",
    "location",
    "attendees",
    "participants",
}
STEP_SECTION_SHARE = 0.5  # ordered items must be at least this share of a section's blocks
ROW_SPLIT_MIN_ROWS = 6  # data rows; smaller tables stay whole in their section
ROW_SPLIT_MIN_CHARS = 1500
LONG_SECTION_CHARS = 2500
WINDOW_WORDS, WINDOW_OVERLAP = 300, 50

_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,4})[.)]?\s+(?=\S)")
_PART = re.compile(
    r"^((?:Part|Section|Chapter|Appendix|Annex|Annexure|Schedule|Module|Unit|Lesson|Article|"
    r"Clause|Exhibit)\s+[A-Z0-9IVXivx]{1,5})\b"
)
_DASHES = (" — ", " – ", " - ", ": ")


def norm_key(k: str) -> str:
    return re.sub(r"[^a-z ]+", "", k.lower()).strip()


def is_metadata_table(b: Block) -> bool:
    if b.type != "table" or not (2 <= len(b.rows) <= 12):
        return False
    rows = _kv_rows(b)
    if len(rows) < 2 or not all(len(r) == 2 for r in rows):
        return False
    keys = [r[0] for r in rows]
    if any(len(k.split()) > 4 or re.search(r"\d", k) for k in keys):
        return False
    return sum(1 for k in keys if norm_key(k) in META_KEYS) >= 2


def _kv_rows(b: Block) -> list[list[str]]:
    """Non-empty cells per row, without a leading one-cell caption row (a spreadsheet often
    puts the table's name, e.g. "Document", above its key/value rows)."""
    rows = [[c for c in r if c] for r in b.rows]
    if rows and len(rows[0]) <= 1:
        rows = rows[1:]
    return rows


def table_kv(b: Block) -> dict[str, str]:
    return {r[0]: r[1] for r in _kv_rows(b) if len(r) == 2}


def heading_label(text: str) -> tuple[str | None, str]:
    """(label, title) from a heading: "4.2 Price tolerance" -> ("4.2", "Price tolerance")."""
    m = _NUMBERED.match(text)
    if m:
        return m.group(1), text[m.end() :].strip()
    m = _PART.match(text)
    if m:
        rest = text[m.end() :].lstrip(" —–-:.").strip()
        return m.group(1), rest or text
    for sep in _DASHES:
        if sep in text:
            head, rest = text.split(sep, 1)
            if 1 <= len(head.split()) <= 4 and len(head) <= 40:
                return head.strip(), rest.strip()
    return None, text


# ---------------------------------------------------------------- data shapes


@dataclass
class DocPart:
    """One document within an episode."""

    ordinal: int
    heading: Block | None  # the top-level heading that starts it (packs only)
    label: str | None  # "Part C", "Video 1"
    title: str | None
    meta_kv: dict[str, str]  # its header table
    preamble: list[Block]  # title lines before the first heading
    blocks: list[Block]  # content, headings included
    container_title: str | None = None  # the file's own title, for packs


@dataclass
class PassageDraft:
    key: str  # unique within the document: locator + occurrence
    segment_kind: str
    locator: str
    heading_path: list[str]
    section_title: str | None
    text: str
    ordinal: int
    leaf: bool
    parent_key: str | None = None
    speaker: str | None = None
    position: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- structure repair


def _body_size(blocks: list[Block]) -> float | None:
    c = Counter()
    for b in blocks:
        if b.type == "paragraph" and b.meta.get("font_size"):
            c[b.meta["font_size"]] += len(b.text)
    return c.most_common(1)[0][0] if c else None


def infer_headings(
    blocks: list[Block], repair: Callable[[list[str]], list[int]] | None = None
) -> list[Block]:
    """Promote paragraphs to headings when no heading styles exist.

    Signals: numbering (`4.2 Title`, `Part C — ...`), short bold or all-caps lines, larger fonts.
    When signals are only visual (or contradictory) and `repair` is given, an LLM assigns levels.
    """
    if any(b.type == "heading" and b.style != "subject" for b in blocks):
        return blocks
    body = _body_size(blocks)
    cands: list[tuple[int, int | None, str]] = []  # (index, level or None, signal)
    for i, b in enumerate(blocks):
        if b.type != "paragraph" or len(b.text) > 100 or b.text.endswith((".", ",", ";")):
            continue
        m = _NUMBERED.match(b.text)
        if m and not re.match(r"^\d+(\.\d+)?\s*(%|per|days?|hours?)", b.text):
            cands.append((i, m.group(1).count(".") + 1, "number"))
        elif _PART.match(b.text):
            cands.append((i, 1, "part"))
        elif (
            b.meta.get("bold")
            or b.meta.get("all_caps")
            or (body and (b.meta.get("font_size") or 0) >= body * 1.2)
        ):
            cands.append((i, None, "visual"))
    if not cands:
        return blocks
    paragraphs = sum(1 for b in blocks if b.type == "paragraph")
    doubtful = any(lvl is None for _, lvl, _ in cands) or len(cands) > 0.6 * max(paragraphs, 1)
    levels: dict[int, int | None] = {i: lvl for i, lvl, _ in cands}
    if doubtful and repair is not None:
        assigned = repair([blocks[i].text for i, _, _ in cands])
        levels = {i: (lv or None) for (i, _, _), lv in zip(cands, assigned, strict=False)}
    elif doubtful:
        # Without repair: numbered and part signals only; visual lines get level 1 if few.
        visual = [i for i, lvl, _ in cands if lvl is None]
        for i in visual:
            levels[i] = 1 if len(visual) <= 0.3 * max(paragraphs, 1) else None
    out = []
    for i, b in enumerate(blocks):
        lvl = levels.get(i)
        if lvl:
            out.append(
                Block(
                    "heading",
                    b.text,
                    level=lvl,
                    page=b.page,
                    bbox=b.bbox,
                    style="inferred",
                    position=b.position,
                    meta=b.meta,
                )
            )
        else:
            out.append(b)
    return out


# ---------------------------------------------------------------- documents


def split_documents(blocks: list[Block]) -> list[DocPart]:
    blocks = [b for b in blocks if b.type != "header_footer"]
    heads = [b for b in blocks if b.type == "heading" and b.style != "subject"]
    top = min((b.level or 1 for b in heads), default=None)
    first_head = next((i for i, b in enumerate(blocks) if b in heads), None)
    if first_head is None:  # no headings: only a leading header table counts as preamble
        first_head = 1 if blocks and is_metadata_table(blocks[0]) else 0
    preamble = blocks[:first_head]
    pre_meta = next((b for b in preamble if is_metadata_table(b)), None)
    container_title = _title_of(preamble)

    starts = [i for i, b in enumerate(blocks) if b in heads and (b.level or 1) == top]
    opens_with_meta = [
        i for i in starts if any(is_metadata_table(x) for x in blocks[i + 1 : i + 3])
    ]
    if pre_meta is None and len(opens_with_meta) >= 2:
        parts = []
        for n, i in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(blocks)
            body = blocks[i + 1 : end]
            meta_b = next((b for b in body[:2] if is_metadata_table(b)), None)
            label, title = heading_label(blocks[i].text)
            parts.append(
                DocPart(
                    ordinal=n + 1,
                    heading=blocks[i],
                    label=label,
                    title=title,
                    meta_kv=table_kv(meta_b) if meta_b else {},
                    preamble=[],
                    blocks=[b for b in body if b is not meta_b],
                    container_title=container_title,
                )
            )
        return parts
    # A lone top-level heading that opens the file (a Markdown or HTML H1) is the title when a
    # header table or deeper headings follow it; its sections become the top level.
    lone = len(starts) == 1 and starts[0] == first_head
    if lone and not _NUMBERED.match(blocks[first_head].text):
        title_block = blocks[first_head]
        after = blocks[first_head + 1 : first_head + 3]
        deeper = any(b in heads and (b.level or 1) > top for b in blocks[first_head + 1 :])
        meta_after = next((b for b in after if is_metadata_table(b)), None)
        if pre_meta is None and (meta_after is not None or deeper):
            title_para = Block(
                "paragraph", title_block.text, meta={**title_block.meta, "title": True}
            )
            pre = [b for b in preamble if b is not pre_meta] + [title_para]
            body = [b for b in blocks[first_head + 1 :] if b is not meta_after]
            return [
                DocPart(
                    ordinal=0,
                    heading=None,
                    label=None,
                    title=title_block.text,
                    meta_kv=table_kv(meta_after) if meta_after else {},
                    preamble=pre,
                    blocks=body,
                )
            ]
    pre = [b for b in preamble if b is not pre_meta]
    return [
        DocPart(
            ordinal=0,
            heading=None,
            label=None,
            title=container_title,
            meta_kv=table_kv(pre_meta) if pre_meta else {},
            preamble=pre,
            blocks=blocks[first_head:],
        )
    ]


def _title_of(preamble: list[Block]) -> str | None:
    """The most prominent short preamble line (title style, else the largest font)."""
    cands = [b for b in preamble if b.type in ("paragraph", "heading") and len(b.text) < 160]
    if not cands:
        return None
    titled = [b for b in cands if b.meta.get("title") or b.style == "subject"]
    if titled:
        return titled[0].text
    sized = [b for b in cands if b.meta.get("font_size")]
    if sized:
        return max(sized, key=lambda b: b.meta["font_size"]).text
    return None


# ---------------------------------------------------------------- passages


@dataclass
class _Section:
    heading: Block | None
    label: str | None
    title: str | None
    level: int
    content: list[Block] = field(default_factory=list)
    children: list[_Section] = field(default_factory=list)


def _tree(doc: DocPart) -> _Section:
    root = _Section(doc.heading, doc.label, doc.title, 0)
    stack = [root]
    for b in doc.blocks:
        if b.type == "heading" and b.style != "subject":
            label, title = heading_label(b.text)
            lvl = b.level or 1
            while len(stack) > 1 and stack[-1].level >= lvl:
                stack.pop()
            node = _Section(b, label, title, lvl)
            stack[-1].children.append(node)
            stack.append(node)
        else:
            stack[-1].content.append(b)
    return root


class _Builder:
    def __init__(self) -> None:
        self.out: list[PassageDraft] = []
        self.seen: Counter[str] = Counter()

    def add(
        self,
        kind: str,
        locator: str,
        path: list[str],
        title: str | None,
        text: str,
        leaf: bool,
        parent: str | None = None,
        **kw: Any,
    ) -> str:
        self.seen[locator] += 1
        key = f"{locator}#{self.seen[locator]}"
        self.out.append(
            PassageDraft(
                key=key,
                segment_kind=kind,
                locator=locator,
                heading_path=path,
                section_title=title,
                text=text.strip(),
                ordinal=len(self.out),
                leaf=leaf,
                parent_key=parent,
                **kw,
            )
        )
        return key


def _subtree_text(sec: _Section) -> str:
    parts = []
    if sec.heading is not None:
        parts.append(sec.heading.text)
    parts += [block_text(b) for b in sec.content if not is_metadata_table(b)]
    parts += [_subtree_text(c) for c in sec.children]
    return "\n\n".join(p for p in parts if p)


def _turn_passages(
    bld: _Builder,
    turns: list[Block],
    label: str,
    path: list[str],
    title: str | None,
    parent: str | None,
) -> None:
    i = 0
    while i < len(turns):
        t = turns[i]
        group = [t]
        nxt = turns[i + 1] if i + 1 < len(turns) else None
        if (
            nxt is not None
            and t.text.rstrip().endswith("?")
            and t.speaker
            and nxt.speaker
            and nxt.speaker != t.speaker
        ):
            group.append(nxt)  # a question joins the answer that follows it
            i += 1
        anchor = group[-1]
        if anchor.time:
            stamp = f"[{anchor.time}]" if anchor.time_style == "bracket" else anchor.time
            locator = f"{label} {stamp}" if label else stamp
        else:
            locator = f"{label} message" if label else "message"
        bld.add(
            "turn" if anchor.time_style != "plain" else "note",
            locator,
            path,
            title,
            "\n".join(block_text(b) for b in group),
            leaf=True,
            parent=parent,
            speaker=anchor.speaker,
            position={"time": anchor.time, **anchor.position},
            meta={"question_joined": len(group) > 1},
        )
        i += 1


SMALL_SHEET_ROWS = 30


def _records(bld: _Builder, table: Block, label: str, path: list[str], title: str | None) -> None:
    header, rows = table.rows[0], table.rows[1:]
    sheet = table.position.get("sheet") or label
    first = table.position.get("first_row", 1)
    # A small sheet is a reference table (grades, rates): one retrievable passage holds all of
    # it. A large one is a data export: a summary, with the rows as records only.
    small = len(rows) <= SMALL_SHEET_ROWS
    desc = (
        f"Sheet {sheet}: {len(rows)} rows. Columns: {', '.join(h for h in header if h)}.\n\n"
        + table_to_markdown([header, *(rows if small else rows[:3])])
    )
    parent = bld.add(
        "table", label, path, title, desc, leaf=small, position={"sheet": sheet, "rows": len(rows)}
    )
    for n, r in enumerate(rows, 1):
        text = "; ".join(f"{h}: {v}" for h, v in zip(header, r, strict=False) if v)
        bld.add(
            "record",
            f"{sheet} row {n}",
            path,
            title,
            text,
            leaf=True,
            parent=parent,
            position={"sheet": sheet, "row": first + n},
        )


def _row_passages(
    bld: _Builder, table: Block, label: str, path: list[str], title: str | None, parent: str | None
) -> None:
    header = table.rows[0]
    for n, r in enumerate(table.rows[1:], 1):
        bld.add(
            "table_row",
            label,
            path,
            title,
            table_to_markdown([header, r]),
            leaf=True,
            parent=parent,
            position={**table.position, "table_row": n},
            meta={"row": n},
        )


def _split_long(text: str) -> list[str]:
    paras = [p for p in text.split("\n\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) > LONG_SECTION_CHARS:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def _section_passages(bld: _Builder, sec: _Section, path: list[str], parent: str | None) -> None:
    label = sec.label or (" › ".join(path[-2:]) if path else "document")
    content = [b for b in sec.content if not is_metadata_table(b)]
    turns = [b for b in content if b.type == "turn"]
    ordered = [b for b in content if b.type == "list_item" and b.meta.get("ordered")]
    big_tables = [
        b
        for b in content
        if b.type == "table"
        and (
            b.meta.get("spreadsheet")
            or len(b.rows) - 1 >= ROW_SPLIT_MIN_ROWS
            or len(table_to_markdown(b.rows)) > ROW_SPLIT_MIN_CHARS
        )
    ]
    has_kids = bool(sec.children)
    whole = (
        _subtree_text(sec)
        if sec.heading is not None
        else "\n\n".join(block_text(b) for b in content)
    )

    splits = (
        bool(turns)
        or bool(big_tables)
        or (len(ordered) >= 2 and len(ordered) >= STEP_SECTION_SHARE * len(content))
    )
    # The section itself: a parent (context) passage when it has children or splits.
    own = "\n\n".join(
        block_text(b)
        for b in content
        if b not in turns and b not in big_tables and not (splits and b in ordered)
    )
    head_text = sec.heading.text if sec.heading is not None else ""
    if has_kids or splits:
        sec_key = bld.add(
            "section", label, path, sec.title, whole, leaf=False, parent=parent, position=_pos(sec)
        )
        if own.strip() and (has_kids or (splits and len(own) > 40)):
            bld.add(
                "section",
                label,
                path,
                sec.title,
                f"{head_text}\n\n{own}".strip(),
                leaf=True,
                parent=sec_key,
                position=_pos(sec),
                meta={"intro": True},
            )
    else:
        sec_key = parent
        text = f"{head_text}\n\n{own}".strip() if own.strip() else ""
        if text:
            chunks = _split_long(text) if len(text) > LONG_SECTION_CHARS else [text]
            for k, chunk in enumerate(chunks, 1):
                bld.add(
                    "section",
                    label,
                    path,
                    sec.title,
                    chunk,
                    leaf=True,
                    parent=parent,
                    position=_pos(sec),
                    meta={"chunk": k} if len(chunks) > 1 else {},
                )

    if turns:
        turn_label = sec.label or (path[-1] if path and sec.heading is not None else "")
        _turn_passages(bld, turns, turn_label, path, sec.title, sec_key)
    if len(ordered) >= 2 and splits:
        for n, b in enumerate(ordered, 1):
            bld.add(
                "step",
                f"{label}, step {n}",
                path,
                sec.title,
                b.text,
                leaf=True,
                parent=sec_key,
                position={**b.position, "step": n},
            )
    for t in big_tables:
        if t.meta.get("spreadsheet"):
            _records(bld, t, label, path, sec.title)
        else:
            _row_passages(bld, t, label, path, sec.title, sec_key)
    for child in sec.children:
        child_path = [*path, child.heading.text] if child.heading is not None else path
        _section_passages(bld, child, child_path, sec_key)


def _pos(sec: _Section) -> dict[str, Any]:
    h = sec.heading
    if h is None:
        return {}
    return {k: v for k, v in {"page": h.page, **h.position}.items() if v is not None}


def _windows(blocks: list[Block]) -> list[tuple[str, int | None]]:
    words: list[tuple[str, int | None]] = []
    for b in blocks:
        words += [(w, b.page) for w in block_text(b).split()]
    out = []
    step = WINDOW_WORDS - WINDOW_OVERLAP
    for start in range(0, max(len(words), 1), step):
        chunk = words[start : start + WINDOW_WORDS]
        if chunk:
            out.append((" ".join(w for w, _ in chunk), chunk[0][1]))
        if start + WINDOW_WORDS >= len(words):
            break
    return out


def segment(doc: DocPart) -> list[PassageDraft]:
    bld = _Builder()
    root_path = [doc.heading.text] if doc.heading is not None else []
    if doc.preamble:
        pre = "\n\n".join(block_text(b) for b in doc.preamble if b.type != "table")
        if pre.strip():
            bld.add("preamble", "preamble", root_path, None, pre, leaf=True)
    root = _tree(doc)
    structured = root.children or any(
        b.type in ("turn", "table", "list_item") for b in root.content
    )
    text_len = sum(len(b.text) for b in root.content)
    if not structured and text_len > LONG_SECTION_CHARS:
        for n, (text, page) in enumerate(_windows(root.content), 1):
            loc = f"p. {page}, ¶{n}" if page else f"¶{n}"
            bld.add("window", loc, root_path, doc.title, text, leaf=True, position={"page": page})
        return bld.out
    if root.heading is None:  # a single document: top-level sections have no parent passage
        if root.content:
            loose = _Section(None, None, doc.title, 0, content=root.content)
            _section_passages(bld, loose, root_path, None)
        for child in root.children:
            _section_passages(bld, child, [*root_path, child.heading.text], None)
    else:
        _section_passages(bld, root, root_path, None)
    return bld.out
